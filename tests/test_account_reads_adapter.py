"""The three read-only account reads of `BinanceUsdmAdapter` (plan 21-03, D-01, D-02, D-04).

The adapter is exercised over a fake SDK serving the SDK models built from the generated
recorded-Demo fixtures (`tests/fixtures/phase21/recorded_demo/`, demo-observed, not mainnet).
Every read is a signed GET through `_sdk_call` and the shared REST gate and is never retried.
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
    AccountInformationV3Response,
)
from src.adapters.binance_ratelimit_gate import (
    RateLimitBanActive,
    RateLimitPauseActive,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import (
    AccountAssetRow,
    AccountInformationSnapshot,
    BinanceUsdmAdapter,
    SignedCallPolicyMissing,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from structlog.testing import capture_logs

from tests.support.limits import TEST_ONLY_RECV_WINDOW_MS as RECV_WINDOW
from tests.support.limits import test_only_signed_call_policy

RECORDED = Path(__file__).resolve().parent / "fixtures" / "phase21" / "recorded_demo"
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


def _information_payload(fixture: Any = None) -> AccountInformationV3Response:
    model = AccountInformationV3Response.from_dict(
        fixture if fixture is not None else _fixture("account_information_v3.json")
    )
    assert model is not None
    return model


# --------------------------------------------------------------------------- account_information


async def test_account_information_snapshot_reads_the_recorded_demo_equity() -> None:
    adapter, rest, _ = _adapter({"account_information_v3": _information_payload()})
    snapshot = await adapter.account_information_snapshot()
    assert isinstance(snapshot, AccountInformationSnapshot)
    assert snapshot.total_margin_balance == Decimal("4999.09343961")
    assert snapshot.total_wallet_balance == Decimal("4999.09343961")
    assert snapshot.total_unrealized_profit == Decimal("0.00000000")
    rows = {row.asset: row for row in snapshot.assets}
    assert rows["USDT"] == AccountAssetRow(
        asset="USDT",
        wallet_balance=Decimal("4999.09343961"),
        unrealized_profit=Decimal("0.00000000"),
        margin_balance=Decimal("4999.09343961"),
    )
    assert rows["USDC"].wallet_balance == Decimal("5000.00000000")
    assert rows["BTC"].wallet_balance == Decimal("0.01000000")
    amounts = [snapshot.total_margin_balance, snapshot.total_wallet_balance]
    amounts += [snapshot.total_unrealized_profit]
    for row in snapshot.assets:
        amounts += [row.wallet_balance, row.unrealized_profit, row.margin_balance]
    assert all(isinstance(amount, Decimal) for amount in amounts)
    assert isinstance(snapshot.assets, tuple)
    assert [row.asset for row in snapshot.assets][:2] == ["FDUSD", "U"]  # response order kept
    assert rest.calls("account_information_v3") == 1
    assert rest.kwargs["account_information_v3"] == [{"recv_window": RECV_WINDOW}]


async def test_account_information_snapshot_is_refused_by_a_paused_gate_before_the_sdk() -> None:
    adapter, rest, gate = _adapter({"account_information_v3": _information_payload()})
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    with pytest.raises(RateLimitPauseActive):
        await adapter.account_information_snapshot()
    assert rest.calls("account_information_v3") == 0


async def test_account_information_snapshot_is_refused_by_a_ban_before_the_sdk() -> None:
    adapter, rest, gate = _adapter({"account_information_v3": _information_payload()})
    gate.record(ExchangeErrorCategory.IP_BANNED, None)
    with pytest.raises(RateLimitBanActive):
        await adapter.account_information_snapshot()
    assert rest.calls("account_information_v3") == 0


async def test_account_information_snapshot_without_a_policy_fails_closed() -> None:
    adapter, rest, _ = _adapter({"account_information_v3": _information_payload()}, policy=False)
    with pytest.raises(SignedCallPolicyMissing):
        await adapter.account_information_snapshot()
    assert rest.calls("account_information_v3") == 0


async def test_account_information_snapshot_propagates_an_sdk_error_and_never_retries() -> None:
    adapter, rest, _ = _adapter({"account_information_v3": _information_payload()})
    boom = BadRequestError("rejected", -1000)
    rest.errors["account_information_v3"] = boom
    with pytest.raises(BadRequestError) as caught:
        await adapter.account_information_snapshot()
    assert caught.value is boom
    assert rest.calls("account_information_v3") == 1


BAD_TEXT = [None, "", "abc", "NaN", "Infinity", "-Infinity"]


def _with_total(field: str, value: Any) -> dict[str, Any]:
    data = _fixture("account_information_v3.json")
    if value is None:
        del data[field]
    else:
        data[field] = value
    return data


def _with_asset_field(field: str, value: Any) -> dict[str, Any]:
    data = _fixture("account_information_v3.json")
    if value is None:
        del data["assets"][5][field]
    else:
        data["assets"][5][field] = value
    return data


@pytest.mark.parametrize("bad", BAD_TEXT)
@pytest.mark.parametrize(
    "field", ["totalMarginBalance", "totalWalletBalance", "totalUnrealizedProfit"]
)
async def test_a_bad_total_raises_naming_the_field_only(field: str, bad: Any) -> None:
    payload = _information_payload(_with_total(field, bad))
    adapter, _, _ = _adapter({"account_information_v3": payload})
    with pytest.raises(ValueError, match=field) as caught:
        await adapter.account_information_snapshot()
    if isinstance(bad, str) and bad:
        assert bad not in str(caught.value).replace(field, "")


@pytest.mark.parametrize("bad", BAD_TEXT)
@pytest.mark.parametrize("field", ["walletBalance", "unrealizedProfit", "marginBalance"])
async def test_a_bad_asset_amount_raises_naming_the_field_only(field: str, bad: Any) -> None:
    payload = _information_payload(_with_asset_field(field, bad))
    adapter, _, _ = _adapter({"account_information_v3": payload})
    with pytest.raises(ValueError, match=field) as caught:
        await adapter.account_information_snapshot()
    if isinstance(bad, str) and bad:
        assert bad not in str(caught.value).replace(field, "")


@pytest.mark.parametrize("bad", [None, ""])
async def test_a_missing_or_empty_asset_name_raises(bad: Any) -> None:
    payload = _information_payload(_with_asset_field("asset", bad))
    adapter, _, _ = _adapter({"account_information_v3": payload})
    with pytest.raises(ValueError, match="asset"):
        await adapter.account_information_snapshot()


async def test_a_missing_assets_list_raises_and_an_empty_one_is_kept_empty() -> None:
    data = _fixture("account_information_v3.json")
    del data["assets"]
    adapter, _, _ = _adapter({"account_information_v3": _information_payload(data)})
    with pytest.raises(ValueError, match="assets"):
        await adapter.account_information_snapshot()
    data["assets"] = []
    adapter, _, _ = _adapter({"account_information_v3": _information_payload(data)})
    snapshot = await adapter.account_information_snapshot()
    assert snapshot.assets == ()
    assert snapshot.total_margin_balance == Decimal("4999.09343961")


async def test_a_successful_account_information_read_logs_no_balance() -> None:
    adapter, _, _ = _adapter({"account_information_v3": _information_payload()})
    with capture_logs() as events:
        await adapter.account_information_snapshot()
    text = json.dumps(events, default=str)
    for digits in ("4999", "5000.0", "0.01000000"):
        assert digits not in text
