"""Public market-data adapter split (phase 16, plan 16-03; SC6, D-13, D040).

`BinancePublicMarketData` carries the public data surface of the exchange adapter so the SHADOW
runtime can read market data without constructing the order adapter. These tests pin that the
order adapter delegates to it with identical output, and that the public module has no order,
cancel, account or position surface and no credential source. No network is used: a fake SDK
client stands in for the REST client.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import src.adapters.binance_public as public_mod
import src.adapters.binance_usdm as usdm_mod
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    CheckServerTimeResponse,
    ExchangeInformationResponse,
    ExchangeInformationResponseSymbolsInner,
    ExchangeInformationResponseSymbolsInnerFiltersInner,
    GetFundingRateHistoryResponseInner,
    OpenInterestResponse,
)
from src.adapters.binance_public import BinancePublicMarketData
from src.adapters.binance_usdm import BinanceUsdmAdapter

# Source: live GET /fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=2, 2026-10-07 (16-RESEARCH.md,
# "Real-shaped fixture rows"; prices are exchange data).
ROW0 = [
    1791360000000,
    "84094.70",
    "84139.20",
    "83902.50",
    "83909.90",
    "5844.590",
    1791363599999,
    "490868445.00560",
    179437,
    "2473.352",
    "207729461.40190",
    "0",
]
ROW1 = [
    1791363600000,
    "83909.90",
    "83965.50",
    "83603.00",
    "83749.00",
    "7821.908",
    1791367199999,
    "655296503.76730",
    125134,
    "3519.234",
    "294835835.39980",
    "0",
]


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    """Records every call so a test can assert which SDK method was reached."""

    def __init__(self, rows: list[list[Any]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def kline_candlestick_data(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("kline_candlestick_data", kwargs))
        return _FakeResponse(self._rows)


class _FakeSdk:
    def __init__(self, rest: _FakeRest) -> None:
        self.rest_api = rest


def _sdk() -> _FakeSdk:
    return _FakeSdk(_FakeRest([ROW0, ROW1]))


def test_public_klines_equal_order_adapter_klines() -> None:
    public = asyncio.run(BinancePublicMarketData(sdk_client=_sdk()).klines("BTCUSDT", "1h"))  # type: ignore[arg-type]
    order = asyncio.run(BinanceUsdmAdapter(sdk_client=_sdk()).klines("BTCUSDT", "1h"))  # type: ignore[arg-type]
    assert len(public) == 2
    assert public == order
    assert [repr(k) for k in public] == [repr(k) for k in order]


def test_kline_is_one_type_re_exported_by_the_order_adapter() -> None:
    assert usdm_mod.Kline is public_mod.Kline


# --------------------------------------------------------------------------- #
# Task 2: the rest of the public surface returns what the order adapter returns.
# --------------------------------------------------------------------------- #

MARK_ROW = [
    1791360000000,
    "84090.10",
    "84130.00",
    "83900.00",
    "83905.50",
    "0",
    1791363599999,
    "0",
    60,
    "0",
    "0",
    "0",
]


def _price_filter() -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="PRICE_FILTER", tick_size="0.10"
    )


def _lot_filter() -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="LOT_SIZE", step_size="0.001", min_qty="0.001", max_qty="1000"
    )


def _notional_filter() -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="MIN_NOTIONAL", notional="5"
    )


def _percent_price_filter() -> Any:
    return ExchangeInformationResponseSymbolsInnerFiltersInner(
        filter_type="PERCENT_PRICE",
        multiplier_up="1.0500",
        multiplier_down="0.9500",
        multiplier_decimal="4",
    )


def _symbol_record() -> Any:
    return ExchangeInformationResponseSymbolsInner(
        symbol="BTCUSDT",
        contract_type="PERPETUAL",
        status="TRADING",
        base_asset="BTC",
        quote_asset="USDT",
        margin_asset="USDT",
        filters=[_price_filter(), _lot_filter(), _notional_filter(), _percent_price_filter()],
        delivery_date=4133404800000,
    )


class _FullFakeRest(_FakeRest):
    """Every public market-data SDK call, with fixed real-shaped payloads."""

    def mark_price_kline_candlestick_data(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("mark_price_kline_candlestick_data", kwargs))
        return _FakeResponse([MARK_ROW])

    def open_interest(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("open_interest", kwargs))
        return _FakeResponse(
            OpenInterestResponse(symbol="BTCUSDT", open_interest="81234.567", time=1791360000000)
        )

    def open_interest_statistics(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("open_interest_statistics", kwargs))
        return _FakeResponse(
            [
                SimpleNamespace(
                    symbol="BTCUSDT", sum_open_interest="81000.5", timestamp=1791356400000
                ),
                SimpleNamespace(
                    symbol="BTCUSDT", sum_open_interest="81234.567", timestamp=1791360000000
                ),
            ]
        )

    def get_funding_rate_history(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("get_funding_rate_history", kwargs))
        return _FakeResponse(
            [
                GetFundingRateHistoryResponseInner(
                    symbol="BTCUSDT",
                    funding_time=1791360000000,
                    funding_rate="0.00010000",
                    mark_price="84000.12345678",
                ),
                GetFundingRateHistoryResponseInner(
                    symbol="BTCUSDT",
                    funding_time=1791388800000,
                    funding_rate="-0.00005000",
                    mark_price="",
                ),
            ]
        )

    def check_server_time(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("check_server_time", kwargs))
        return _FakeResponse(CheckServerTimeResponse(server_time=1791360123456))

    def exchange_information(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("exchange_information", kwargs))
        return _FakeResponse(ExchangeInformationResponse(symbols=[_symbol_record()]))


def _full_sdk() -> _FakeSdk:
    return _FakeSdk(_FullFakeRest([ROW0, ROW1]))


def _both() -> tuple[BinancePublicMarketData, BinanceUsdmAdapter]:
    return (
        BinancePublicMarketData(sdk_client=_full_sdk()),  # type: ignore[arg-type]
        BinanceUsdmAdapter(sdk_client=_full_sdk()),  # type: ignore[arg-type]
    )


def test_every_public_method_equals_the_order_adapter_method() -> None:
    public, order = _both()
    assert asyncio.run(public.mark_klines("BTCUSDT", "1h")) == asyncio.run(
        order.mark_klines("BTCUSDT", "1h")
    )
    assert asyncio.run(public.funding_rate("BTCUSDT")) == asyncio.run(order.funding_rate("BTCUSDT"))
    assert asyncio.run(public.server_time()) == asyncio.run(order.server_time())
    assert asyncio.run(public.exchange_info()) == asyncio.run(order.exchange_info())
    assert asyncio.run(public.open_interest("BTCUSDT")) == asyncio.run(
        order.open_interest("BTCUSDT")
    )
    assert asyncio.run(public.open_interest_statistics("BTCUSDT", "1h")) == asyncio.run(
        order.open_interest_statistics("BTCUSDT", "1h")
    )


def test_the_public_values_are_the_expected_real_shaped_values() -> None:
    """Pins the shared output itself, so equality cannot hold between two empty results."""
    public, _ = _both()
    marks = asyncio.run(public.mark_klines("BTCUSDT", "1h"))
    assert [(m.close, m.price_tick_count) for m in marks] == [(Decimal("83905.50"), 60)]
    funding = asyncio.run(public.funding_rate("BTCUSDT"))
    assert [f.funding_rate for f in funding] == [Decimal("0.00010000"), Decimal("-0.00005000")]
    assert funding[0].mark_price == Decimal("84000.12345678")
    assert funding[1].mark_price is None
    assert asyncio.run(public.server_time()) == datetime.fromtimestamp(1791360123.456, tz=UTC)
    (info,) = asyncio.run(public.exchange_info())
    assert (info.price_tick_size, info.quantity_step_size, info.min_notional) == (
        Decimal("0.10"),
        Decimal("0.001"),
        Decimal("5"),
    )
    assert info.percent_price_multiplier_decimals == 4
    oi = asyncio.run(public.open_interest_statistics("BTCUSDT", "1h"))
    assert [(o.open_interest, o.source) for o in oi] == [
        (Decimal("81000.5"), "research"),
        (Decimal("81234.567"), "research"),
    ]


def test_every_moved_value_type_is_one_object_in_both_modules() -> None:
    for name in ("Kline", "MarkKline", "OiSnapshot", "FundingTick", "SymbolFilters"):
        assert getattr(usdm_mod, name) is getattr(public_mod, name), name


def test_order_adapter_reaches_the_sdk_through_the_public_class() -> None:
    sdk = _full_sdk()
    adapter = BinanceUsdmAdapter(sdk_client=sdk)  # type: ignore[arg-type]
    assert adapter._public._sdk is sdk  # one client serves both surfaces
    asyncio.run(adapter.server_time())
    assert [name for name, _ in sdk.rest_api.calls] == ["check_server_time"]


# --------------------------------------------------------------------------- #
# Task 2: the public module has no order, cancel, account or position surface.
# --------------------------------------------------------------------------- #

FORBIDDEN_METHODS = frozenset(
    {
        "place_entry",
        "place_algo_protective",
        "cancel_normal_order",
        "cancel_algo_order",
        "query_order_by_client",
        "query_algo_order_by_client",
        "snapshot_open_normal_orders",
        "snapshot_open_algo_orders",
        "snapshot_positions",
        "get_position_mode",
        "user_commission_rate",
    }
)
ALLOWED_REST_CALLS = frozenset(
    {
        "kline_candlestick_data",
        "mark_price_kline_candlestick_data",
        "open_interest",
        "open_interest_statistics",
        "get_funding_rate_history",
        "check_server_time",
        "exchange_information",
    }
)
ENV_NAMES = frozenset({"environ", "getenv", "getenvb"})
CREDENTIAL_KEYWORDS = frozenset({"api_key", "api_secret", "private_key", "private_key_passphrase"})
PUBLIC_MODULE = Path(public_mod.__file__)


def _public_surface_violations(path: Path) -> list[str]:
    """AST scan of one module for any order, account, credential or environment surface.

    Reports, sorted: a function or method named like an order, cancel, query, snapshot,
    position-mode or commission method; an SDK client attribute other than `rest_api`; a
    `rest_api.<call>` outside the public market-data allowlist; any `environ` / `getenv`
    reference; a credential keyword argument that is not the literal None; and any
    reference to `BinanceUsdmAdapter` or the `binance_usdm` module.

    Not covered: a name or attribute built at runtime (getattr with a computed string).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name in FORBIDDEN_METHODS:
                found.append(f"{node.lineno}: defines order-surface method {node.name}")
        if isinstance(node, ast.Attribute):
            inner = node.value
            if (
                isinstance(inner, ast.Attribute)
                and inner.attr == "_sdk"
                and node.attr != "rest_api"
            ):
                found.append(f"{node.lineno}: SDK client attribute {node.attr} (only rest_api)")
            if isinstance(inner, ast.Attribute) and inner.attr == "rest_api":
                if node.attr not in ALLOWED_REST_CALLS:
                    found.append(f"{node.lineno}: rest_api call {node.attr} is not public data")
            if node.attr in ENV_NAMES:
                found.append(f"{node.lineno}: reads the environment via {node.attr}")
        if isinstance(node, ast.Name):
            if node.id in ENV_NAMES:
                found.append(f"{node.lineno}: reads the environment via {node.id}")
            if node.id == "BinanceUsdmAdapter":
                found.append(f"{node.lineno}: references BinanceUsdmAdapter")
        if isinstance(node, ast.keyword) and node.arg in CREDENTIAL_KEYWORDS:
            is_none = isinstance(node.value, ast.Constant) and node.value.value is None
            if not is_none:
                found.append(f"{node.value.lineno}: credential keyword {node.arg} is not None")
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("binance_usdm"):
            found.append(f"{node.lineno}: imports binance_usdm")
        if isinstance(node, ast.Import) and any(
            a.name.endswith("binance_usdm") for a in node.names
        ):
            found.append(f"{node.lineno}: imports binance_usdm")
    return sorted(found)


def test_public_module_has_no_order_account_or_credential_surface() -> None:
    assert _public_surface_violations(PUBLIC_MODULE) == []


def test_public_module_does_not_import_os() -> None:
    tree = ast.parse(PUBLIC_MODULE.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.split(".")[0] == "os" for name in imported)


def test_public_class_builds_its_client_with_a_none_key_and_secret() -> None:
    """The default client is created from an explicit configuration with no credential."""
    config = BinancePublicMarketData()._sdk._rest_api_config  # type: ignore[attr-defined]
    assert config.api_key is None
    assert config.api_secret is None
    assert config.private_key is None


def test_the_surface_checker_reports_a_seeded_place_entry(tmp_path: Path) -> None:
    """Negative control: the checker is not vacuous."""
    seeded = tmp_path / "seeded.py"
    seeded.write_text(
        "import os\n"
        "from src.adapters.binance_usdm import BinanceUsdmAdapter\n"
        "class Bad:\n"
        "    async def place_entry(self):\n"
        "        key = os.environ['K']\n"
        "        await self._sdk.websocket_api.x()\n"
        "        await self._sdk.rest_api.new_order(symbol='A')\n"
        "        return BinanceUsdmAdapter(api_key='abc')\n"
        "    def get_position_mode(self):\n"
        "        return ConfigurationRestAPI(api_key='abc', api_secret=os.getenv('S'))\n",
        encoding="utf-8",
    )
    found = "\n".join(_public_surface_violations(seeded))
    assert "order-surface method place_entry" in found
    assert "order-surface method get_position_mode" in found
    assert "SDK client attribute websocket_api" in found
    assert "rest_api call new_order is not public data" in found
    assert "reads the environment via environ" in found
    assert "reads the environment via getenv" in found
    assert "credential keyword api_key is not None" in found
    assert "credential keyword api_secret is not None" in found
    assert "references BinanceUsdmAdapter" in found
    assert "imports binance_usdm" in found


def test_the_surface_checker_accepts_a_clean_module(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    clean.write_text(
        "class Ok:\n"
        "    async def klines(self):\n"
        "        return await self._sdk.rest_api.kline_candlestick_data()\n"
        "    def make(self):\n"
        "        return ConfigurationRestAPI(api_key=None, api_secret=None)\n",
        encoding="utf-8",
    )
    assert _public_surface_violations(clean) == []
