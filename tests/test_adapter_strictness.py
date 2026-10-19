"""Strictness tests for the Binance USDM adapter (WR-03).

D-09 flag-never-fabricate: a missing exchangeInfo filter field or a
malformed open-interest-statistics row must raise loudly — never become
a plausible zero / empty string / silently dropped row.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pytest
from binance_sdk_derivatives_trading_usds_futures import (
    BadRequestError,
    TooManyRequestsError,
)
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    CheckServerTimeResponse,
    ExchangeInformationResponse,
    ExchangeInformationResponseSymbolsInner,
    ExchangeInformationResponseSymbolsInnerFiltersInner,
    GetFundingRateHistoryResponseInner,
    UserCommissionRateResponse,
)
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import (
    INVALID_SYMBOL_CODE,
    BinanceUsdmAdapter,
    CommissionRates,
    is_invalid_symbol_error,
)

from tests.support.limits import TEST_ONLY_RECV_WINDOW_MS, test_only_signed_call_policy


def _price_filter(tick_size: str | None) -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="PRICE_FILTER",
        tick_size=tick_size,
    )


def _lot_filter() -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="LOT_SIZE",
        step_size="0.001",
        min_qty="0.001",
        max_qty="1000",
    )


def _notional_filter() -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="MIN_NOTIONAL",
        notional="5",
    )


def _symbol(
    filters: list[Any],
    *,
    symbol: str | None = "BTCUSDT",
    delivery_date: int | None = None,
    status: str = "TRADING",
) -> Any:
    return ExchangeInformationResponseSymbolsInner(
        symbol=symbol,
        contract_type="PERPETUAL",
        status=status,
        base_asset="BTC",
        quote_asset="USDT",
        margin_asset="USDT",
        filters=filters,
        delivery_date=delivery_date,
    )


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    def __init__(
        self,
        info: Any = None,
        oi_rows: Any = None,
        commission: Any = None,
        commission_error: Exception | None = None,
        funding_rows: Any = None,
        server_time: Any = None,
    ) -> None:
        self._info = info
        self._oi_rows = oi_rows or []
        self._commission = commission
        self._commission_error = commission_error
        self._funding_rows = funding_rows if funding_rows is not None else []
        self._server_time = server_time
        self.commission_calls: list[tuple[str, int | None]] = []

    def get_funding_rate_history(
        self,
        *,
        symbol: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> _FakeResponse:
        return _FakeResponse(self._funding_rows)

    def check_server_time(self) -> _FakeResponse:
        return _FakeResponse(self._server_time)

    def user_commission_rate(self, symbol: str, recv_window: int | None = None) -> _FakeResponse:
        self.commission_calls.append((symbol, recv_window))
        if self._commission_error is not None:
            raise self._commission_error
        return _FakeResponse(self._commission)

    def exchange_information(self) -> _FakeResponse:
        return _FakeResponse(self._info)

    def open_interest_statistics(
        self,
        *,
        symbol: str,
        period: str,
        limit: int,
    ) -> _FakeResponse:
        return _FakeResponse(self._oi_rows)


class _FakeSdk:
    def __init__(self, rest: _FakeRest) -> None:
        self.rest_api = rest


def _adapter_with_info(symbols: list[Any]) -> BinanceUsdmAdapter:
    info = ExchangeInformationResponse(symbols=symbols)
    return BinanceUsdmAdapter(sdk_client=_FakeSdk(_FakeRest(info=info)))  # type: ignore[arg-type]


def test_exchange_info_raises_on_missing_tick_size() -> None:
    """A PRICE_FILTER without tick_size must raise, not persist zero."""
    adapter = _adapter_with_info(
        [_symbol([_price_filter(None), _lot_filter(), _notional_filter()])]
    )
    with pytest.raises(ValueError, match="missing numeric field"):
        asyncio.run(adapter.exchange_info())


def test_exchange_info_raises_on_missing_symbol_identity() -> None:
    """A symbol record without a symbol must join the drift failure."""
    adapter = _adapter_with_info(
        [
            _symbol(
                [_price_filter("0.01"), _lot_filter(), _notional_filter()],
                symbol=None,
            )
        ]
    )
    with pytest.raises(ValueError, match="drift"):
        asyncio.run(adapter.exchange_info())


def test_exchange_info_accepts_complete_record() -> None:
    """A complete record still projects to SymbolFilters (no false raise)."""
    adapter = _adapter_with_info(
        [_symbol([_price_filter("0.01"), _lot_filter(), _notional_filter()])]
    )
    out = asyncio.run(adapter.exchange_info())
    assert len(out) == 1
    assert out[0].symbol == "BTCUSDT"
    assert str(out[0].price_tick_size) == "0.01"


class _OiRow:
    def __init__(
        self,
        symbol: str | None,
        timestamp: int | None,
        total: str | None,
    ) -> None:
        self.symbol = symbol
        self.timestamp = timestamp
        self.sum_open_interest = total


def test_oi_statistics_raises_on_malformed_row() -> None:
    """A harvest row missing timestamp/measurement raises, never drops."""
    rest = _FakeRest(oi_rows=[_OiRow("BTCUSDT", None, "123.4")])
    adapter = BinanceUsdmAdapter(sdk_client=_FakeSdk(rest))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="missing fields"):
        asyncio.run(adapter.open_interest_statistics(symbol="BTCUSDT", period="5m"))


def test_oi_statistics_accepts_complete_rows() -> None:
    """Complete harvest rows still project with the research source tag."""
    rest = _FakeRest(oi_rows=[_OiRow("BTCUSDT", 1_700_000_000_000, "123.4")])
    adapter = BinanceUsdmAdapter(sdk_client=_FakeSdk(rest))  # type: ignore[arg-type]
    out = asyncio.run(adapter.open_interest_statistics(symbol="BTCUSDT", period="5m"))
    assert len(out) == 1
    assert out[0].source == "research"


# --------------------------------------------------------------------------- #
# user_commission_rate (Phase 12, plan 12-05): strict, never fabricates a rate.
# --------------------------------------------------------------------------- #


def _commission_adapter(
    payload: Any = None,
    error: Exception | None = None,
) -> tuple[BinanceUsdmAdapter, _FakeRest]:
    rest = _FakeRest(commission=payload, commission_error=error)
    # Plan 18-13: a signed call needs the TEST_ONLY policy and the one shared gate.
    policy = test_only_signed_call_policy()
    gate = RestRateLimitGate(
        policy=policy.rate_limit, clock=lambda: datetime(2026, 10, 16, tzinfo=UTC)
    )
    adapter = BinanceUsdmAdapter(
        sdk_client=_FakeSdk(rest),  # type: ignore[arg-type]
        signed_call_policy=policy,
        rest_gate=gate,
    )
    return adapter, rest


def _commission_response(
    *,
    symbol: str | None = "BTCUSDT",
    maker: str | None = "0.0002",
    taker: str | None = "0.0004",
    rpi: str | None = "0.00005",
) -> Any:
    return UserCommissionRateResponse(
        symbol=symbol,
        maker_commission_rate=maker,
        taker_commission_rate=taker,
        rpi_commission_rate=rpi,
    )


def test_user_commission_rate_projects_frozen_dataclass() -> None:
    adapter, rest = _commission_adapter(_commission_response())
    out = asyncio.run(adapter.user_commission_rate("BTCUSDT"))
    assert out == CommissionRates(
        symbol="BTCUSDT",
        maker_rate=Decimal("0.0002"),
        taker_rate=Decimal("0.0004"),
    )
    assert rest.commission_calls == [("BTCUSDT", TEST_ONLY_RECV_WINDOW_MS)]
    with pytest.raises(AttributeError):
        out.taker_rate = Decimal("0.1")  # type: ignore[misc]


def test_user_commission_rate_accepts_zero_taker() -> None:
    adapter, _ = _commission_adapter(_commission_response(taker="0"))
    out = asyncio.run(adapter.user_commission_rate("BTCUSDT"))
    assert out.taker_rate == Decimal("0")


def test_user_commission_rate_ignores_missing_rpi() -> None:
    adapter, _ = _commission_adapter(_commission_response(rpi=None))
    out = asyncio.run(adapter.user_commission_rate("BTCUSDT"))
    assert out.taker_rate == Decimal("0.0004")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"taker": None},
        {"maker": None},
        {"taker": "abc"},
        {"maker": "abc"},
        {"taker": "NaN"},
        {"taker": "Infinity"},
        {"maker": "NaN"},
        {"taker": "-0.0001"},
        {"maker": "-0.0001"},
        {"taker": "0.5"},
        {"maker": "0.5"},
        {"taker": ""},
        {"symbol": None},
        {"symbol": "ETHUSDT"},
    ],
)
def test_user_commission_rate_raises_on_malformed_response(kwargs: dict[str, str | None]) -> None:
    adapter, _ = _commission_adapter(_commission_response(**kwargs))
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(adapter.user_commission_rate("BTCUSDT"))
    assert "BTCUSDT" in str(excinfo.value)


def test_user_commission_rate_raises_on_none_response() -> None:
    adapter, _ = _commission_adapter(None)
    with pytest.raises(ValueError, match="BTCUSDT"):
        asyncio.run(adapter.user_commission_rate("BTCUSDT"))


def test_user_commission_rate_error_names_field_not_secrets() -> None:
    adapter, _ = _commission_adapter(_commission_response(taker="abc"))
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(adapter.user_commission_rate("BTCUSDT"))
    text = str(excinfo.value)
    assert "takerCommissionRate" in text
    for forbidden in ("signature", "http", "apiKey", "api_key", "secret"):
        assert forbidden.lower() not in text.lower()


def test_user_commission_rate_propagates_sdk_exception() -> None:
    boom = RuntimeError("sdk down")
    adapter, rest = _commission_adapter(error=boom)
    with pytest.raises(RuntimeError, match="sdk down"):
        asyncio.run(adapter.user_commission_rate("BTCUSDT"))
    assert len(rest.commission_calls) == 1


# --------------------------------------------------------------------------- #
# Phase 13 plan 04: adapter facts for historical data (D-08, D-25, D-26, Pitfall 9).
# --------------------------------------------------------------------------- #


def test_exchange_info_exposes_delivery_date() -> None:
    """deliveryDate flows to SymbolFilters.delivery_date_ms unchanged (D-26)."""
    filters = [_price_filter("0.01"), _lot_filter(), _notional_filter()]
    adapter = _adapter_with_info(
        [
            _symbol(filters, symbol="FTTUSDT", delivery_date=1668398400000, status="SETTLING"),
            _symbol(filters, symbol="ETHUSDT"),
            _symbol(filters, symbol="BTCUSDT", delivery_date=4133404800000),
        ]
    )
    out = {f.symbol: f for f in asyncio.run(adapter.exchange_info())}
    assert out["FTTUSDT"].delivery_date_ms == 1668398400000
    assert out["ETHUSDT"].delivery_date_ms is None
    # The perpetual sentinel is passed through; consumers decide what is past.
    assert out["BTCUSDT"].delivery_date_ms == 4133404800000


def _funding_row(mark_price: str | None, *, rate: str | None = "0.0001", ts: int | None = 1) -> Any:
    return GetFundingRateHistoryResponseInner(
        symbol="BTCUSDT",
        funding_rate=rate,
        funding_time=ts,
        mark_price=mark_price,
    )


def _funding_adapter(rows: list[Any]) -> BinanceUsdmAdapter:
    sdk = _FakeSdk(_FakeRest(funding_rows=rows))
    return BinanceUsdmAdapter(sdk_client=sdk)  # type: ignore[arg-type]


def test_funding_row_with_empty_mark_price_parses_as_none() -> None:
    """Historical funding rows carry markPrice "" (Pitfall 9); never fabricated as 0."""
    adapter = _funding_adapter(
        [
            _funding_row(""),
            _funding_row(None, ts=2),
            _funding_row("83751.55144203", ts=3),
        ]
    )
    ticks = asyncio.run(adapter.funding_rate("BTCUSDT"))
    assert [t.mark_price for t in ticks] == [None, None, Decimal("83751.55144203")]


def test_funding_row_with_malformed_mark_price_still_raises() -> None:
    adapter = _funding_adapter([_funding_row("abc")])
    with pytest.raises(InvalidOperation):
        asyncio.run(adapter.funding_rate("BTCUSDT"))


@pytest.mark.parametrize(
    "row",
    [_funding_row("1.0", rate=None), _funding_row("1.0", ts=None)],
)
def test_funding_row_missing_rate_or_time_still_raises(row: Any) -> None:
    adapter = _funding_adapter([row])
    with pytest.raises(ValueError, match="missing fields"):
        asyncio.run(adapter.funding_rate("BTCUSDT"))


def test_server_time_returns_utc_datetime() -> None:
    from datetime import UTC, datetime

    sdk = _FakeSdk(_FakeRest(server_time=CheckServerTimeResponse(server_time=1790770020000)))
    adapter = BinanceUsdmAdapter(sdk_client=sdk)  # type: ignore[arg-type]
    got = asyncio.run(adapter.server_time())
    assert got == datetime.fromtimestamp(1790770020, tz=UTC)
    assert got.tzinfo is not None


def test_server_time_missing_value_raises() -> None:
    sdk = _FakeSdk(_FakeRest(server_time=CheckServerTimeResponse(server_time=None)))
    adapter = BinanceUsdmAdapter(sdk_client=sdk)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="server_time"):
        asyncio.run(adapter.server_time())


def test_invalid_symbol_predicate() -> None:
    assert INVALID_SYMBOL_CODE == -1121
    invalid = BadRequestError(error_message="Invalid symbol.", status_code=-1121)
    assert is_invalid_symbol_error(invalid)
    assert not is_invalid_symbol_error(BadRequestError(error_message="x", status_code=-1100))
    assert not is_invalid_symbol_error(ValueError("x"))
    assert not is_invalid_symbol_error(TooManyRequestsError(error_message="slow", status_code=429))


def _position_row(**overrides: Any) -> Any:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
        PositionInformationV3ResponseInner,
    )

    fields: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "position_side": "BOTH",
        "position_amt": "0.010",
        "entry_price": "50000.1",
        "break_even_price": "50020.1",
        "mark_price": "50010.0",
        "un_realized_profit": "0.0999",
        "liquidation_price": "0",
        "notional": "500.1",
        "margin_asset": "USDT",
        "update_time": 1790770020000,
    }
    return PositionInformationV3ResponseInner(**{**fields, **overrides})


def test_position_row_with_a_missing_amount_raises_instead_of_reading_flat() -> None:
    """CR-01: a dropped positionAmt must not become Decimal(0) (the sweeper's flat check)."""
    from src.adapters.binance_usdm import _row_to_position_snapshot

    with pytest.raises(ValueError, match="positionAmt"):
        _row_to_position_snapshot(_position_row(position_amt=None))


def test_position_row_with_a_complete_amount_projects_the_signed_decimal() -> None:
    from src.adapters.binance_usdm import _row_to_position_snapshot

    snapshot = _row_to_position_snapshot(_position_row(position_amt="-0.010"))
    assert snapshot is not None
    assert snapshot.position_amt == Decimal("-0.010")
    flat = _row_to_position_snapshot(_position_row(position_amt="0.000"))
    assert flat is not None
    assert flat.position_amt == Decimal("0.000")
