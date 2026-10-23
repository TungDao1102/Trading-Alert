"""The two paged REST reads the daily loss uses as its arbiter (plan 21-08, D-09, D-04, D-20).

`user_trades_in_window` (GET /fapi/v1/userTrades) and `income_in_window` (GET /fapi/v1/income)
are exercised over a fake SDK that serves one scripted page per call. The trade rows come from
the generated recorded-Demo fixtures (`tests/fixtures/phase21/recorded_demo/`, demo-observed,
not mainnet). The income rows are SYNTHETIC (built here from the SDK model): the recorded Demo
income reads of 2026-10-22 had zero rows, so the funding source is unverified on Demo.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from binance_common.errors import BadRequestError
from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    AccountTradeListResponseInner,
    GetIncomeHistoryIncomeTypeEnum,
    GetIncomeHistoryResponseInner,
)
from src.adapters.binance_ratelimit_gate import (
    RateLimitBanActive,
    RateLimitPauseActive,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    IncomeRow,
    SignedCallPolicyMissing,
    UserTradeRow,
)
from src.domain.exchange_errors import ExchangeErrorCategory

from tests.support.limits import TEST_ONLY_RECV_WINDOW_MS as RECV_WINDOW
from tests.support.limits import test_only_signed_call_policy

RECORDED = Path(__file__).resolve().parent / "fixtures" / "phase21" / "recorded_demo"
START = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# The recorded SL-triggered close (Demo, order 28645789207, trade 549733079).
TRIGGER_TIME_MS = 1792670963058
TRIGGER_ORDER_ID = 28645789207
TRIGGER_TRADE_ID = 549733079


def _utc(ms: int) -> datetime:
    return EPOCH + timedelta(milliseconds=ms)


def _ms(value: datetime) -> int:
    return (value - EPOCH) // timedelta(milliseconds=1)


WINDOW_START = _utc(TRIGGER_TIME_MS - 3_600_000)
WINDOW_END = _utc(TRIGGER_TIME_MS + 1_000)


def _fixture(name: str) -> Any:
    return json.loads((RECORDED / name).read_text(encoding="utf-8"))


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class PagedRest:
    """Serves one scripted page per call of a method name and records every call's kwargs."""

    def __init__(self, pages: dict[str, list[Any]]) -> None:
        self._pages = {name: list(items) for name, items in pages.items()}
        self.kwargs: dict[str, list[dict[str, Any]]] = {}
        self.errors: dict[str, BaseException] = {}

    def calls(self, name: str) -> int:
        return len(self.kwargs.get(name, []))

    def __getattr__(self, name: str) -> Callable[..., _Response]:
        if name.startswith("_") or name not in self._pages:
            raise AttributeError(name)

        def _call(*args: Any, **kwargs: Any) -> _Response:
            assert args == ()
            self.kwargs.setdefault(name, []).append(dict(kwargs))
            error = self.errors.get(name)
            if error is not None:
                raise error
            queue = self._pages[name]
            assert queue, f"unexpected extra {name} call"
            return _Response(queue.pop(0))

        return _call


def _gate() -> RestRateLimitGate:
    return RestRateLimitGate(policy=test_only_signed_call_policy().rate_limit, clock=lambda: START)


def _adapter(
    pages: dict[str, list[Any]], *, policy: bool = True
) -> tuple[BinanceUsdmAdapter, PagedRest, RestRateLimitGate]:
    rest = PagedRest(pages)
    gate = _gate()
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        rest_gate=gate if policy else None,
        signed_call_policy=test_only_signed_call_policy() if policy else None,
    )
    return adapter, rest, gate


def _trade(row: dict[str, Any]) -> AccountTradeListResponseInner:
    model = AccountTradeListResponseInner.from_dict(row)
    assert model is not None
    return model


def _bracket_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = _fixture("user_trades_triggered_bracket.json")
    return rows


def _later(row: dict[str, Any], *, ids: int, ms: int) -> dict[str, Any]:
    """A copy of a recorded row moved to a later id and time (test construction)."""
    return {**row, "id": row["id"] + ids, "time": row["time"] + ms}


async def _trades(
    adapter: BinanceUsdmAdapter, *, symbol: str = "BTCUSDT"
) -> tuple[UserTradeRow, ...]:
    return await adapter.user_trades_in_window(
        symbol=symbol, start_utc=WINDOW_START, end_utc=WINDOW_END
    )


# --------------------------------------------------------------------- user_trades_in_window


async def test_the_recorded_triggered_close_is_read_over_two_pages() -> None:
    adapter, rest, _ = _adapter(
        {"account_trade_list": [[_trade(r) for r in _bracket_rows()], []]},
    )
    rows = await _trades(adapter)
    assert rows == (
        UserTradeRow(
            symbol="BTCUSDT",
            order_id=TRIGGER_ORDER_ID,
            trade_id=TRIGGER_TRADE_ID,
            realized_pnl=Decimal("-0.00327999"),
            commission=Decimal("0.02616201"),
            commission_asset="USDT",
            margin_asset="USDT",
            time_utc=_utc(TRIGGER_TIME_MS),
        ),
    )
    assert isinstance(rows[0].realized_pnl, Decimal) and isinstance(rows[0].commission, Decimal)
    assert rest.kwargs["account_trade_list"] == [
        {
            "symbol": "BTCUSDT",
            "start_time": _ms(WINDOW_START),
            "end_time": _ms(WINDOW_END),
            "recv_window": RECV_WINDOW,
        },
        {"symbol": "BTCUSDT", "from_id": TRIGGER_TRADE_ID + 1, "recv_window": RECV_WINDOW},
    ]


async def test_the_recorded_commission_case_parses_with_exact_decimals() -> None:
    recorded = _fixture("user_trades_commission_case.json")
    assert [row["id"] for row in recorded] == [549732633, 549732634, 549732632]  # recorded order
    page = [_trade(r) for r in sorted(recorded, key=lambda r: r["id"])]
    adapter, _, _ = _adapter({"account_trade_list": [page, []]})
    start, end = _utc(1792670831000), _utc(1792670832000)
    rows = await adapter.user_trades_in_window(symbol="BTCUSDT", start_utc=start, end_utc=end)
    assert [row.trade_id for row in rows] == [549732632, 549732633, 549732634]
    assert [row.realized_pnl for row in rows] == [
        Decimal("0"),
        Decimal("-0.00584999"),
        Decimal("-0.00350999"),
    ]
    assert [row.commission for row in rows] == [
        Decimal("0.02616332"),
        Decimal("0.01634974"),
        Decimal("0.00980984"),
    ]
    assert {row.order_id for row in rows} == {28645786987, 28645786992}


async def test_the_recorded_order_of_the_commission_case_is_not_ascending_and_fails_closed() -> (
    None
):
    recorded = _fixture("user_trades_commission_case.json")
    adapter, _, _ = _adapter({"account_trade_list": [[_trade(r) for r in recorded], []]})
    with pytest.raises(ValueError, match="strictly"):
        await adapter.user_trades_in_window(
            symbol="BTCUSDT", start_utc=_utc(1792670831000), end_utc=_utc(1792670832000)
        )


async def test_rows_after_the_window_end_are_dropped_and_the_loop_stops_on_a_late_page() -> None:
    row = _bracket_rows()[0]
    late = _later(row, ids=1, ms=5_000)
    adapter, rest, _ = _adapter(
        {
            "account_trade_list": [
                [_trade(row), _trade(late)],
                [_trade(_later(row, ids=2, ms=6_000))],
            ]
        }
    )
    rows = await _trades(adapter)
    assert [r.trade_id for r in rows] == [TRIGGER_TRADE_ID]
    # the second page held only trades after the end: the loop stopped there (two calls).
    assert rest.kwargs["account_trade_list"][1]["from_id"] == TRIGGER_TRADE_ID + 2


async def test_an_empty_first_page_is_an_empty_tuple_after_one_call() -> None:
    adapter, rest, _ = _adapter({"account_trade_list": [[]]})
    assert await _trades(adapter) == ()
    assert rest.calls("account_trade_list") == 1


async def test_rows_of_later_pages_are_collected_in_trade_id_order() -> None:
    row = _bracket_rows()[0]
    second = _later(row, ids=1, ms=10)
    third = _later(row, ids=2, ms=20)
    adapter, rest, _ = _adapter(
        {"account_trade_list": [[_trade(row)], [_trade(second), _trade(third)], []]}
    )
    rows = await _trades(adapter)
    assert [r.trade_id for r in rows] == [
        TRIGGER_TRADE_ID,
        TRIGGER_TRADE_ID + 1,
        TRIGGER_TRADE_ID + 2,
    ]
    assert [call.get("from_id") for call in rest.kwargs["account_trade_list"]] == [
        None,
        TRIGGER_TRADE_ID + 1,
        TRIGGER_TRADE_ID + 3,
    ]
    for call in rest.kwargs["account_trade_list"][1:]:
        assert "start_time" not in call and "end_time" not in call and "limit" not in call


async def test_a_row_of_another_symbol_raises() -> None:
    adapter, _, _ = _adapter(
        {"account_trade_list": [[_trade({**_bracket_rows()[0], "symbol": "ETHUSDT"})]]}
    )
    with pytest.raises(ValueError, match="symbol"):
        await _trades(adapter)


async def test_a_trade_id_that_does_not_grow_across_pages_raises_and_cannot_loop() -> None:
    row = _bracket_rows()[0]
    adapter, rest, _ = _adapter({"account_trade_list": [[_trade(row)], [_trade(row)]]})
    with pytest.raises(ValueError, match="strictly"):
        await _trades(adapter)
    assert rest.calls("account_trade_list") == 2


async def test_trade_ids_that_fall_inside_one_page_raise() -> None:
    row = _bracket_rows()[0]
    page = [_trade(_later(row, ids=1, ms=1)), _trade(row)]
    adapter, _, _ = _adapter({"account_trade_list": [page]})
    with pytest.raises(ValueError, match="strictly"):
        await _trades(adapter)


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "orderId",
        "symbol",
        "realizedPnl",
        "commission",
        "commissionAsset",
        "marginAsset",
        "time",
    ],
)
async def test_a_missing_trade_field_raises_naming_the_field(field: str) -> None:
    row = {key: value for key, value in _bracket_rows()[0].items() if key != field}
    adapter, _, _ = _adapter({"account_trade_list": [[_trade(row)]]})
    with pytest.raises(ValueError, match=field):
        await _trades(adapter)


@pytest.mark.parametrize("field", ["realizedPnl", "commission"])
@pytest.mark.parametrize("text", ["", " 1", "NaN", "Infinity", "1_0", "abc"])
async def test_a_malformed_trade_amount_raises_without_echoing_the_text(
    field: str, text: str
) -> None:
    adapter, _, _ = _adapter(
        {"account_trade_list": [[_trade({**_bracket_rows()[0], field: text})]]}
    )
    with pytest.raises(ValueError, match=field) as caught:
        await _trades(adapter)
    assert text.strip() == "" or text not in str(caught.value)


@pytest.mark.parametrize("field", ["commissionAsset", "marginAsset"])
async def test_an_empty_asset_text_raises(field: str) -> None:
    adapter, _, _ = _adapter({"account_trade_list": [[_trade({**_bracket_rows()[0], field: ""})]]})
    with pytest.raises(ValueError, match=field):
        await _trades(adapter)


async def test_a_bool_trade_id_is_not_an_integer() -> None:
    bad = SimpleNamespace(
        symbol="BTCUSDT",
        id=True,
        order_id=1,
        realized_pnl="0",
        commission="0",
        commission_asset="USDT",
        margin_asset="USDT",
        time=TRIGGER_TIME_MS,
    )
    adapter, _, _ = _adapter({"account_trade_list": [[bad]]})
    with pytest.raises(ValueError, match="id"):
        await _trades(adapter)


@pytest.mark.parametrize("payload", [None, "rows", 7])
async def test_a_page_that_is_not_a_list_raises(payload: Any) -> None:
    adapter, _, _ = _adapter({"account_trade_list": [payload]})
    with pytest.raises(ValueError, match="page"):
        await _trades(adapter)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 10, 22), datetime(2026, 10, 23, tzinfo=UTC)),  # naive start
        (datetime(2026, 10, 22, tzinfo=UTC), datetime(2026, 10, 23)),  # naive end
        (
            datetime(2026, 10, 22, tzinfo=timezone(timedelta(hours=7))),
            datetime(2026, 10, 23, tzinfo=UTC),
        ),  # not UTC
        (datetime(2026, 10, 23, tzinfo=UTC), datetime(2026, 10, 22, tzinfo=UTC)),  # start > end
        (datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 9, tzinfo=UTC)),  # > 7 days
    ],
    ids=["naive_start", "naive_end", "not_utc", "reversed", "longer_than_7_days"],
)
async def test_a_bad_window_raises_before_any_sdk_call(start: datetime, end: datetime) -> None:
    adapter, rest, _ = _adapter({"account_trade_list": [[]]})
    with pytest.raises(ValueError, match="window"):
        await adapter.user_trades_in_window(symbol="BTCUSDT", start_utc=start, end_utc=end)
    assert rest.calls("account_trade_list") == 0


async def test_a_window_of_exactly_seven_days_is_accepted() -> None:
    adapter, rest, _ = _adapter({"account_trade_list": [[]]})
    start = datetime(2026, 10, 15, tzinfo=UTC)
    assert (
        await adapter.user_trades_in_window(
            symbol="BTCUSDT", start_utc=start, end_utc=start + timedelta(days=7)
        )
        == ()
    )
    assert rest.calls("account_trade_list") == 1


async def test_trades_without_a_policy_are_refused_before_any_call() -> None:
    adapter, rest, _ = _adapter({"account_trade_list": [[]]}, policy=False)
    with pytest.raises(SignedCallPolicyMissing):
        await _trades(adapter)
    assert rest.calls("account_trade_list") == 0


@pytest.mark.parametrize(
    ("category", "refusal"),
    [
        (ExchangeErrorCategory.IP_BANNED, RateLimitBanActive),
        (ExchangeErrorCategory.RATE_LIMITED, RateLimitPauseActive),
    ],
)
async def test_trades_are_refused_by_the_shared_gate(
    category: ExchangeErrorCategory, refusal: type[Exception]
) -> None:
    adapter, rest, gate = _adapter({"account_trade_list": [[]]})
    gate.record(category, None)
    with pytest.raises(refusal):
        await _trades(adapter)
    assert rest.calls("account_trade_list") == 0


async def test_an_sdk_error_propagates_unchanged_and_is_never_retried() -> None:
    adapter, rest, _ = _adapter({"account_trade_list": [[]]})
    error = BadRequestError("bad request", -1121)
    rest.errors["account_trade_list"] = error
    with pytest.raises(BadRequestError) as caught:
        await _trades(adapter)
    assert caught.value is error
    assert rest.calls("account_trade_list") == 1


# ------------------------------------------------------------------------ income_in_window


def _income(**changes: Any) -> GetIncomeHistoryResponseInner:
    """SYNTHETIC FUNDING_FEE row built from the SDK model (the recorded income reads had 0 rows)."""
    base: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "incomeType": "FUNDING_FEE",
        "income": "-0.01250000",
        "asset": "USDT",
        "info": "FUNDING_FEE",
        "time": TRIGGER_TIME_MS,
        "tranId": 9_000_001,
        "tradeId": "",
    }
    base.update(changes)
    model = GetIncomeHistoryResponseInner.from_dict(base)
    assert model is not None
    return model


async def _funding(adapter: BinanceUsdmAdapter) -> tuple[IncomeRow, ...]:
    return await adapter.income_in_window(
        income_type="FUNDING_FEE", start_utc=WINDOW_START, end_utc=WINDOW_END
    )


async def test_the_recorded_empty_income_answer_is_an_empty_tuple_after_one_call() -> None:
    assert _fixture("income_funding_empty.json") == []
    adapter, rest, _ = _adapter({"get_income_history": [_fixture("income_funding_empty.json")]})
    assert await _funding(adapter) == ()
    assert rest.kwargs["get_income_history"] == [
        {
            "income_type": GetIncomeHistoryIncomeTypeEnum.FUNDING_FEE,
            "start_time": _ms(WINDOW_START),
            "end_time": _ms(WINDOW_END),
            "page": 1,
            "recv_window": RECV_WINDOW,
        }
    ]


async def test_a_synthetic_funding_row_is_read_and_the_next_page_is_asked_for() -> None:
    adapter, rest, _ = _adapter({"get_income_history": [[_income()], []]})
    rows = await _funding(adapter)
    assert rows == (
        IncomeRow(
            symbol="BTCUSDT",
            income_type="FUNDING_FEE",
            income=Decimal("-0.01250000"),
            asset="USDT",
            tran_id=9_000_001,
            trade_id=None,
            time_utc=_utc(TRIGGER_TIME_MS),
        ),
    )
    assert isinstance(rows[0].income, Decimal)
    assert [call["page"] for call in rest.kwargs["get_income_history"]] == [1, 2]


async def test_account_level_rows_have_no_symbol_and_a_trade_id_is_kept_as_text() -> None:
    page = [_income(symbol="", tranId=2, tradeId="77"), _income(symbol=None, tranId=1, time=1)]
    adapter, _, _ = _adapter({"get_income_history": [page, []]})
    rows = await _funding(adapter)
    assert [row.tran_id for row in rows] == [1, 2]  # ordered by (time, tran_id)
    assert rows[0].symbol is None and rows[0].trade_id is None
    assert rows[1].symbol is None and rows[1].trade_id == "77"


async def test_rows_of_several_pages_are_ordered_by_time_then_transaction_id() -> None:
    adapter, _, _ = _adapter(
        {
            "get_income_history": [
                [_income(tranId=5, time=300)],
                [_income(tranId=3, time=100), _income(tranId=4, time=100)],
                [],
            ]
        }
    )
    assert [(r.time_utc, r.tran_id) for r in await _funding(adapter)] == [
        (_utc(100), 3),
        (_utc(100), 4),
        (_utc(300), 5),
    ]


async def test_a_repeated_transaction_id_across_pages_raises_and_cannot_loop() -> None:
    adapter, rest, _ = _adapter({"get_income_history": [[_income()], [_income()]]})
    with pytest.raises(ValueError, match="tranId"):
        await _funding(adapter)
    assert rest.calls("get_income_history") == 2


async def test_an_income_type_outside_the_sdk_enum_raises_before_any_call() -> None:
    adapter, rest, _ = _adapter({"get_income_history": [[]]})
    with pytest.raises(ValueError, match="income_type"):
        await adapter.income_in_window(
            income_type="NOT_A_TYPE", start_utc=WINDOW_START, end_utc=WINDOW_END
        )
    assert rest.calls("get_income_history") == 0


async def test_a_row_of_another_income_type_raises() -> None:
    adapter, _, _ = _adapter({"get_income_history": [[_income(incomeType="COMMISSION")]]})
    with pytest.raises(ValueError, match="incomeType"):
        await _funding(adapter)


@pytest.mark.parametrize("field", ["income", "asset", "tranId", "time", "incomeType"])
async def test_a_missing_income_field_raises_naming_the_field(field: str) -> None:
    base = {
        "symbol": "BTCUSDT",
        "incomeType": "FUNDING_FEE",
        "income": "1",
        "asset": "USDT",
        "time": TRIGGER_TIME_MS,
        "tranId": 1,
    }
    row = GetIncomeHistoryResponseInner.from_dict({k: v for k, v in base.items() if k != field})
    adapter, _, _ = _adapter({"get_income_history": [[row]]})
    with pytest.raises(ValueError, match=field):
        await _funding(adapter)


@pytest.mark.parametrize("text", ["", "NaN", "Infinity", " 1", "x"])
async def test_a_malformed_income_amount_raises(text: str) -> None:
    adapter, _, _ = _adapter({"get_income_history": [[_income(income=text)]]})
    with pytest.raises(ValueError, match="income"):
        await _funding(adapter)


async def test_the_info_text_is_never_read() -> None:
    class _NoInfo(SimpleNamespace):
        @property
        def info(self) -> str:
            raise AssertionError("the free-text info field must never be read")

    row = _NoInfo(
        symbol="BTCUSDT",
        income_type="FUNDING_FEE",
        income="-0.5",
        asset="USDT",
        time=TRIGGER_TIME_MS,
        tran_id=3,
        trade_id=None,
    )
    adapter, _, _ = _adapter({"get_income_history": [[row], []]})
    assert [r.income for r in await _funding(adapter)] == [Decimal("-0.5")]
    assert "info" not in IncomeRow.__dataclass_fields__


async def test_a_bad_income_window_raises_before_any_call() -> None:
    adapter, rest, _ = _adapter({"get_income_history": [[]]})
    with pytest.raises(ValueError, match="window"):
        await adapter.income_in_window(
            income_type="FUNDING_FEE", start_utc=WINDOW_END, end_utc=WINDOW_START
        )
    assert rest.calls("get_income_history") == 0


async def test_income_without_a_policy_or_behind_the_gate_sends_nothing() -> None:
    adapter, rest, _ = _adapter({"get_income_history": [[]]}, policy=False)
    with pytest.raises(SignedCallPolicyMissing):
        await _funding(adapter)
    adapter, rest, gate = _adapter({"get_income_history": [[]]})
    gate.record(ExchangeErrorCategory.IP_BANNED, None)
    with pytest.raises(RateLimitBanActive):
        await _funding(adapter)
    assert rest.calls("get_income_history") == 0
