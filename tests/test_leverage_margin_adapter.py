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
    NotionalAndLeverageBracketsResponse,
    SymbolConfigurationResponse,
)
from src.adapters.binance_ratelimit_gate import (
    RateLimitBanActive,
    RateLimitPauseActive,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    LeverageBracketRow,
    SignedCallPolicyMissing,
    SymbolConfigSnapshot,
    SymbolLeverageBrackets,
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


# --------------------------------------------------------------------------- leverageBracket

BRACKETS = "notional_and_leverage_brackets"


def _brackets_payload(fixture: Any = None) -> Any:
    """The SDK oneOf wrapper the real `notional_and_leverage_brackets` returns."""
    model = NotionalAndLeverageBracketsResponse.from_dict(
        fixture if fixture is not None else _fixture("leverage_brackets.json")
    )
    assert model is not None
    return model


def _bracket(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "bracket": 1,
        "initial_leverage": 125,
        "notional_floor": 0,
        "notional_cap": 50000,
        "maint_margin_ratio": 0.004,
        "cum": 0.0,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _entry(brackets: Any = "default", **overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "notional_coef": None,
        "brackets": [_bracket()] if brackets == "default" else brackets,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def test_leverage_brackets_snapshot_reads_the_recorded_demo_table_as_exact_decimals() -> None:
    adapter, rest, _ = _adapter({BRACKETS: _brackets_payload()})
    table = await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    assert isinstance(table, SymbolLeverageBrackets)
    assert table.symbol == "BTCUSDT"
    assert table.notional_coef is None
    assert isinstance(table.brackets, tuple) and len(table.brackets) == 10
    assert all(isinstance(row, LeverageBracketRow) for row in table.brackets)
    assert [row.bracket for row in table.brackets] == list(range(1, 11))  # response order kept
    assert table.brackets[0] == LeverageBracketRow(
        bracket=1,
        initial_leverage=125,
        notional_floor=Decimal("0"),
        notional_cap=Decimal("50000"),
        maint_margin_ratio=Decimal("0.004"),
        cum=Decimal("0"),
    )
    assert table.brackets[3] == LeverageBracketRow(
        bracket=4,
        initial_leverage=20,
        notional_floor=Decimal("3000000"),
        notional_cap=Decimal("20000000"),
        maint_margin_ratio=Decimal("0.025"),
        cum=Decimal("46300"),
    )
    for row in table.brackets:
        for number in (row.notional_floor, row.notional_cap, row.maint_margin_ratio, row.cum):
            assert isinstance(number, Decimal)
    assert rest.calls(BRACKETS) == 1
    assert rest.kwargs[BRACKETS] == [{"symbol": "BTCUSDT", "recv_window": RECV_WINDOW}]


async def test_the_maintenance_ratio_is_decimal_of_the_repr_not_of_the_float() -> None:
    adapter, _, _ = _adapter({BRACKETS: _brackets_payload()})
    table = await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    ratio = table.brackets[0].maint_margin_ratio
    assert ratio == Decimal("0.004")
    # Decimal(float) exposes the binary expansion: it must NOT be what the adapter returns
    # (22-RESEARCH Pitfall 4, T-22-01).
    assert Decimal(0.004) != Decimal("0.004")
    assert ratio != Decimal(0.004)
    assert str(ratio) == "0.004"


async def test_the_object_answer_shape_parses_to_the_same_result() -> None:
    entry = _fixture("leverage_brackets.json")[0]
    # SDK 17.4.0 quirk: the object shape (Response2) declares `cum` as StrictInt only, while the
    # list shape accepts StrictFloat too. The recorded sums are whole numbers, so the derived
    # object answer carries them as integers; the parsed result must be the same.
    for bracket in entry["brackets"]:
        assert bracket["cum"] == int(bracket["cum"])
        bracket["cum"] = int(bracket["cum"])
    adapter, _, _ = _adapter({BRACKETS: _brackets_payload(entry)})
    from_object = await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    adapter, _, _ = _adapter({BRACKETS: _brackets_payload()})
    from_list = await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    assert from_object == from_list


async def test_a_present_notional_coef_is_carried_as_a_decimal_and_not_interpreted() -> None:
    adapter, _, _ = _adapter({BRACKETS: [_entry(notional_coef=1.5)]})
    table = await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    assert table.notional_coef == Decimal("1.5")
    adapter, _, _ = _adapter({BRACKETS: [_entry(notional_coef=1)]})
    assert (await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")).notional_coef == Decimal(1)


@pytest.mark.parametrize(
    "answer",
    [
        [],
        [_entry(), _entry()],
        [_entry(symbol="ETHUSDT")],
        _entry(symbol="ETHUSDT"),
        None,
    ],
    ids=["empty", "two_entries", "other_symbol", "other_symbol_object", "no_data"],
)
async def test_a_wrong_number_of_entries_or_another_symbol_raises(answer: Any) -> None:
    adapter, _, _ = _adapter({BRACKETS: answer})
    with pytest.raises(ValueError, match="leverage bracket"):
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")


@pytest.mark.parametrize(
    ("field", "attribute", "bad"),
    [
        ("maintMarginRatio", "maint_margin_ratio", None),
        ("maintMarginRatio", "maint_margin_ratio", True),
        ("maintMarginRatio", "maint_margin_ratio", float("nan")),
        ("maintMarginRatio", "maint_margin_ratio", float("inf")),
        ("maintMarginRatio", "maint_margin_ratio", -0.004),
        ("maintMarginRatio", "maint_margin_ratio", "0.004"),
        ("cum", "cum", None),
        ("cum", "cum", False),
        ("cum", "cum", float("nan")),
        ("cum", "cum", float("-inf")),
        ("cum", "cum", -1.0),
        ("initialLeverage", "initial_leverage", True),
        ("initialLeverage", "initial_leverage", 0),
        ("initialLeverage", "initial_leverage", None),
        ("bracket", "bracket", None),
        ("bracket", "bracket", True),
        ("notionalFloor", "notional_floor", None),
        ("notionalFloor", "notional_floor", 1.5),
        ("notionalCap", "notional_cap", None),
        ("notionalCap", "notional_cap", True),
    ],
)
async def test_a_bad_bracket_field_raises_naming_the_field_only(
    field: str, attribute: str, bad: Any
) -> None:
    adapter, _, _ = _adapter({BRACKETS: [_entry([_bracket(**{attribute: bad})])]})
    with pytest.raises(ValueError, match=field) as caught:
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    message = str(caught.value)
    if isinstance(bad, str):
        assert bad not in message.replace(field, "")
    assert "nan" not in message.lower().replace(field.lower(), "")


@pytest.mark.parametrize("brackets", [None, [], "x"], ids=["missing", "empty", "not_a_list"])
async def test_a_missing_or_empty_bracket_list_raises(brackets: Any) -> None:
    adapter, _, _ = _adapter({BRACKETS: [_entry(brackets)]})
    with pytest.raises(ValueError, match="brackets"):
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")


@pytest.mark.parametrize("bad", [True, "1", float("nan"), -1])
async def test_a_bad_notional_coef_raises(bad: Any) -> None:
    adapter, _, _ = _adapter({BRACKETS: [_entry(notional_coef=bad)]})
    with pytest.raises(ValueError, match="notionalCoef"):
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")


async def test_leverage_brackets_snapshot_is_refused_by_a_paused_gate_before_the_sdk() -> None:
    adapter, rest, gate = _adapter({BRACKETS: _brackets_payload()})
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    with pytest.raises(RateLimitPauseActive):
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    assert rest.calls(BRACKETS) == 0


async def test_leverage_brackets_snapshot_is_refused_by_a_ban_before_the_sdk() -> None:
    adapter, rest, gate = _adapter({BRACKETS: _brackets_payload()})
    gate.record(ExchangeErrorCategory.IP_BANNED, None)
    with pytest.raises(RateLimitBanActive):
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    assert rest.calls(BRACKETS) == 0


async def test_leverage_brackets_snapshot_without_a_policy_fails_closed() -> None:
    adapter, rest, _ = _adapter({BRACKETS: _brackets_payload()}, policy=False)
    with pytest.raises(SignedCallPolicyMissing):
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    assert rest.calls(BRACKETS) == 0


async def test_leverage_brackets_snapshot_propagates_an_sdk_error_and_never_retries() -> None:
    adapter, rest, _ = _adapter({BRACKETS: _brackets_payload()})
    boom = BadRequestError("rejected", -1000)
    rest.errors[BRACKETS] = boom
    with pytest.raises(BadRequestError) as caught:
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    assert caught.value is boom
    assert rest.calls(BRACKETS) == 1


async def test_a_successful_leverage_brackets_read_logs_no_bracket_value() -> None:
    adapter, _, _ = _adapter({BRACKETS: _brackets_payload()})
    with capture_logs() as events:
        await adapter.leverage_brackets_snapshot(symbol="BTCUSDT")
    text = json.dumps(events, default=str)
    for digits in ("0.004", "46300", "20000000", "125"):
        assert digits not in text


# ------------------------------------------------------------------ change_margin_type (22-06)

CHANGE_MARGIN = "change_margin_type"
CHANGE_LEVERAGE = "change_initial_leverage"
# Answer bodies the adapter must never read: a different code, or nothing at all.
_ANSWER = SimpleNamespace(code=999, msg="not trusted")


async def test_change_margin_type_sends_one_signed_call_with_the_sdk_enum() -> None:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
        ChangeMarginTypeMarginTypeEnum,
    )

    adapter, rest, _ = _adapter({CHANGE_MARGIN: _ANSWER})
    result = await adapter.change_margin_type(symbol="BTCUSDT", margin_type="ISOLATED")
    assert result is None
    assert rest.calls(CHANGE_MARGIN) == 1
    assert rest.kwargs[CHANGE_MARGIN] == [
        {
            "symbol": "BTCUSDT",
            "margin_type": ChangeMarginTypeMarginTypeEnum.ISOLATED,
            "recv_window": RECV_WINDOW,
        }
    ]


async def test_change_margin_type_converts_crossed_to_the_crossed_member() -> None:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
        ChangeMarginTypeMarginTypeEnum,
    )

    adapter, rest, _ = _adapter({CHANGE_MARGIN: _ANSWER})
    await adapter.change_margin_type(symbol="ETHUSDT", margin_type="CROSSED")
    assert rest.kwargs[CHANGE_MARGIN][0]["margin_type"] is ChangeMarginTypeMarginTypeEnum.CROSSED


@pytest.mark.parametrize("bad", ["isolated", "", "ISOLATED ", "crossed", "BOTH", None, 1, True])
async def test_change_margin_type_refuses_a_bad_margin_type_before_any_sdk_call(bad: Any) -> None:
    adapter, rest, _ = _adapter({CHANGE_MARGIN: _ANSWER})
    with pytest.raises(ValueError):
        await adapter.change_margin_type(symbol="BTCUSDT", margin_type=bad)
    assert rest.calls(CHANGE_MARGIN) == 0


@pytest.mark.parametrize("bad", ["", None, 5, b"BTCUSDT"])
async def test_change_margin_type_refuses_a_bad_symbol_before_any_sdk_call(bad: Any) -> None:
    adapter, rest, _ = _adapter({CHANGE_MARGIN: _ANSWER})
    with pytest.raises(ValueError):
        await adapter.change_margin_type(symbol=bad, margin_type="ISOLATED")
    assert rest.calls(CHANGE_MARGIN) == 0


async def test_change_margin_type_never_reads_the_answer_body() -> None:
    adapter, rest, _ = _adapter({CHANGE_MARGIN: None})
    assert await adapter.change_margin_type(symbol="BTCUSDT", margin_type="ISOLATED") is None
    assert rest.calls(CHANGE_MARGIN) == 1


async def test_change_margin_type_propagates_the_original_error_after_one_call() -> None:
    adapter, rest, _ = _adapter({CHANGE_MARGIN: _ANSWER})
    boom = BadRequestError("No need to change margin type.", -4046)
    rest.errors[CHANGE_MARGIN] = boom
    with pytest.raises(BadRequestError) as caught:
        await adapter.change_margin_type(symbol="BTCUSDT", margin_type="ISOLATED")
    assert caught.value is boom
    assert rest.calls(CHANGE_MARGIN) == 1


async def test_change_margin_type_without_a_policy_fails_closed() -> None:
    adapter, rest, _ = _adapter({CHANGE_MARGIN: _ANSWER}, policy=False)
    with pytest.raises(SignedCallPolicyMissing):
        await adapter.change_margin_type(symbol="BTCUSDT", margin_type="ISOLATED")
    assert rest.calls(CHANGE_MARGIN) == 0


async def test_change_margin_type_is_refused_by_a_ban_before_the_sdk() -> None:
    adapter, rest, gate = _adapter({CHANGE_MARGIN: _ANSWER})
    gate.record(ExchangeErrorCategory.IP_BANNED, None)
    with pytest.raises(RateLimitBanActive):
        await adapter.change_margin_type(symbol="BTCUSDT", margin_type="ISOLATED")
    assert rest.calls(CHANGE_MARGIN) == 0
