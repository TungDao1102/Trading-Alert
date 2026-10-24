"""The two leverage and margin configuration reads of `BinanceUsdmAdapter` (plan 22-01).

`symbol_config_snapshot` (GET /fapi/v1/symbolConfig) and `leverage_brackets_snapshot`
(GET /fapi/v1/leverageBracket) are exercised over a fake SDK serving the SDK models built from the
generated recorded-Demo fixtures (`tests/fixtures/phase22/recorded_demo/`, demo-observed, not
mainnet). Every read is a signed GET through `_sdk_call` and the shared REST gate and is never
retried (D-01, D-03, D-06).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from binance_common.errors import BadRequestError
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    SymbolConfigurationResponse,
)
from src.adapters.binance_ratelimit_gate import (
    RateLimitBanActive,
    RateLimitPauseActive,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    SignedCallPolicyMissing,
    SymbolConfigSnapshot,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from structlog.testing import capture_logs

from tests.support.limits import TEST_ONLY_RECV_WINDOW_MS as RECV_WINDOW
from tests.support.limits import test_only_signed_call_policy

RECORDED = Path(__file__).resolve().parent / "fixtures" / "phase22" / "recorded_demo"
START = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)


def _fixture(name: str) -> Any:
    return json.loads((RECORDED / name).read_text(encoding="utf-8"))


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class FakeRest:
    """Serves one scripted payload per SDK method name and records every call."""

    def __init__(self, payloads: dict[str, Any]) -> None:
        self._payloads = payloads
        self.kwargs: dict[str, list[dict[str, Any]]] = {}
        self.errors: dict[str, BaseException] = {}

    def calls(self, name: str) -> int:
        return len(self.kwargs.get(name, []))

    def __getattr__(self, name: str) -> Callable[..., _Response]:
        if name.startswith("_") or name not in self._payloads:
            raise AttributeError(name)

        def _call(*args: Any, **kwargs: Any) -> _Response:
            assert args == ()
            self.kwargs.setdefault(name, []).append(dict(kwargs))
            error = self.errors.get(name)
            if error is not None:
                raise error
            return _Response(self._payloads[name])

        return _call


def _gate() -> RestRateLimitGate:
    return RestRateLimitGate(policy=test_only_signed_call_policy().rate_limit, clock=lambda: START)


def _adapter(
    payloads: dict[str, Any], *, policy: bool = True
) -> tuple[BinanceUsdmAdapter, FakeRest, RestRateLimitGate]:
    rest = FakeRest(payloads)
    gate = _gate()
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        rest_gate=gate if policy else None,
        signed_call_policy=test_only_signed_call_policy() if policy else None,
    )
    return adapter, rest, gate


# --------------------------------------------------------------------------- symbolConfig

SYMBOL_CONFIG = "symbol_configuration"


def _config_payload(fixture: Any = None) -> Any:
    models = SymbolConfigurationResponse.from_dict(
        fixture if fixture is not None else _fixture("symbol_config.json")
    )
    assert models is not None
    return models


def _row(**overrides: Any) -> SimpleNamespace:
    """A plain row of the recorded values; used where the SDK model would refuse the value."""
    fields: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "margin_type": "CROSSED",
        "leverage": 20,
        "is_auto_add_margin": False,
        "max_notional_value": "20000000",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def test_symbol_config_snapshot_reads_the_recorded_demo_crossed_x20() -> None:
    adapter, rest, _ = _adapter({SYMBOL_CONFIG: _config_payload()})
    snapshot = await adapter.symbol_config_snapshot(symbol="BTCUSDT")
    assert snapshot == SymbolConfigSnapshot(
        symbol="BTCUSDT",
        margin_type="CROSSED",
        leverage=20,
        is_auto_add_margin=False,
        max_notional_value=Decimal("20000000"),
    )
    assert snapshot.leverage == 20
    assert snapshot.margin_type == "CROSSED"
    assert isinstance(snapshot.max_notional_value, Decimal)
    assert isinstance(snapshot.leverage, int) and not isinstance(snapshot.leverage, bool)
    assert rest.calls(SYMBOL_CONFIG) == 1
    assert rest.kwargs[SYMBOL_CONFIG] == [{"symbol": "BTCUSDT", "recv_window": RECV_WINDOW}]


async def test_a_derived_isolated_answer_parses_the_same_way() -> None:
    # Derived inside the test: the ISOLATED casing has never been observed on Demo, the owner
    # case of D-18 records it (22-RESEARCH A5). This only proves the parser keeps the text.
    data = _fixture("symbol_config.json")
    data[0]["marginType"] = "ISOLATED"
    data[0]["leverage"] = 5
    adapter, _, _ = _adapter({SYMBOL_CONFIG: _config_payload(data)})
    snapshot = await adapter.symbol_config_snapshot(symbol="BTCUSDT")
    assert snapshot.margin_type == "ISOLATED"
    assert snapshot.leverage == 5
    assert snapshot.is_auto_add_margin is False


async def test_symbol_config_snapshot_is_refused_by_a_paused_gate_before_the_sdk() -> None:
    adapter, rest, gate = _adapter({SYMBOL_CONFIG: _config_payload()})
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    with pytest.raises(RateLimitPauseActive):
        await adapter.symbol_config_snapshot(symbol="BTCUSDT")
    assert rest.calls(SYMBOL_CONFIG) == 0


async def test_symbol_config_snapshot_is_refused_by_a_ban_before_the_sdk() -> None:
    adapter, rest, gate = _adapter({SYMBOL_CONFIG: _config_payload()})
    gate.record(ExchangeErrorCategory.IP_BANNED, None)
    with pytest.raises(RateLimitBanActive):
        await adapter.symbol_config_snapshot(symbol="BTCUSDT")
    assert rest.calls(SYMBOL_CONFIG) == 0


async def test_symbol_config_snapshot_without_a_policy_fails_closed() -> None:
    adapter, rest, _ = _adapter({SYMBOL_CONFIG: _config_payload()}, policy=False)
    with pytest.raises(SignedCallPolicyMissing):
        await adapter.symbol_config_snapshot(symbol="BTCUSDT")
    assert rest.calls(SYMBOL_CONFIG) == 0


async def test_symbol_config_snapshot_propagates_an_sdk_error_and_never_retries() -> None:
    adapter, rest, _ = _adapter({SYMBOL_CONFIG: _config_payload()})
    boom = BadRequestError("rejected", -1000)
    rest.errors[SYMBOL_CONFIG] = boom
    with pytest.raises(BadRequestError) as caught:
        await adapter.symbol_config_snapshot(symbol="BTCUSDT")
    assert caught.value is boom
    assert rest.calls(SYMBOL_CONFIG) == 1


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_row(), _row()],
        [_row(symbol="ETHUSDT")],
        None,
    ],
    ids=["empty", "two_rows", "other_symbol", "no_data"],
)
async def test_a_wrong_number_of_rows_or_another_symbol_raises(rows: Any) -> None:
    adapter, _, _ = _adapter({SYMBOL_CONFIG: rows})
    with pytest.raises(ValueError, match="symbol"):
        await adapter.symbol_config_snapshot(symbol="BTCUSDT")


@pytest.mark.parametrize(
    ("field", "attribute", "bad"),
    [
        ("marginType", "margin_type", None),
        ("marginType", "margin_type", ""),
        ("marginType", "margin_type", 3),
        ("leverage", "leverage", None),
        ("leverage", "leverage", True),
        ("leverage", "leverage", "20"),
        ("leverage", "leverage", 0),
        ("leverage", "leverage", -3),
        ("isAutoAddMargin", "is_auto_add_margin", None),
        ("isAutoAddMargin", "is_auto_add_margin", "false"),
        ("isAutoAddMargin", "is_auto_add_margin", 0),
        ("maxNotionalValue", "max_notional_value", None),
        ("maxNotionalValue", "max_notional_value", ""),
        ("maxNotionalValue", "max_notional_value", "abc"),
        ("maxNotionalValue", "max_notional_value", "NaN"),
        ("maxNotionalValue", "max_notional_value", "Infinity"),
        ("maxNotionalValue", "max_notional_value", 20000000),
    ],
)
async def test_a_bad_field_raises_naming_the_field_only(
    field: str, attribute: str, bad: Any
) -> None:
    adapter, _, _ = _adapter({SYMBOL_CONFIG: [_row(**{attribute: bad})]})
    with pytest.raises(ValueError, match=field) as caught:
        await adapter.symbol_config_snapshot(symbol="BTCUSDT")
    message = str(caught.value).replace(field, "")
    if isinstance(bad, str) and bad:
        assert bad not in message


async def test_a_successful_symbol_config_read_logs_no_value() -> None:
    adapter, _, _ = _adapter({SYMBOL_CONFIG: _config_payload()})
    with capture_logs() as events:
        await adapter.symbol_config_snapshot(symbol="BTCUSDT")
    text = json.dumps(events, default=str)
    assert "20000000" not in text
    assert "CROSSED" not in text
