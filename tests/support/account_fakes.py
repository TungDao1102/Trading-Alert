"""Shared fakes for the live account reads (Phase 21, plan 21-07; plan 21-13 reuses them).

* ``ScriptedAccountReader`` stands in for the adapter's three account reads
  (``AccountReadPort``): per call it pops one scripted value, or raises a scripted exception,
  and records the call order. With ``virtual_time`` and ``advance_seconds_per_call`` the virtual
  clock moves during every call, so a ``now_utc`` read before ``refresh()`` is older than the
  reading's stamp (the freshness contract of ``src/execution/account_equity.py``).
* ``build_demo_adapter`` builds the real ``BinanceUsdmAdapter`` over a fake SDK serving the
  committed Phase 21 recorded-Demo fixtures (demo-observed, not mainnet); ``demo_account_snapshots``
  returns the three adapter snapshots parsed from them by the real adapter code.

TEST_ONLY helpers; nothing here is a project value.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    AccountInformationV3Response,
    FuturesAccountBalanceV3Response,
    FuturesAccountConfigurationResponse,
)
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import (
    AccountBalanceRow,
    AccountConfigSnapshot,
    AccountInformationSnapshot,
    BinanceUsdmAdapter,
)

from tests.support.limits import test_only_signed_call_policy
from tests.support.virtual_time import VirtualTime

RECORDED_DEMO = Path(__file__).resolve().parent.parent / "fixtures" / "phase21" / "recorded_demo"
_GATE_START = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)

CONFIG = "account_config_snapshot"
INFORMATION = "account_information_snapshot"
BALANCES = "account_balances_snapshot"


class ScriptedAccountReader:
    """Scripted ``AccountReadPort``; ``responses`` maps a method name to a list of values."""

    def __init__(
        self,
        responses: dict[str, list[object | BaseException]],
        *,
        virtual_time: VirtualTime | None = None,
        advance_seconds_per_call: int = 0,
    ) -> None:
        self._responses = {name: list(values) for name, values in responses.items()}
        self._virtual_time = virtual_time
        self._advance = advance_seconds_per_call
        self.calls: list[str] = []

    def count(self, name: str) -> int:
        return self.calls.count(name)

    async def _serve(self, name: str) -> Any:
        self.calls.append(name)
        if self._virtual_time is not None and self._advance:
            await self._virtual_time.advance(self._advance)
        queue = self._responses.get(name)
        if not queue:
            raise AssertionError(f"no scripted response left for {name}")
        value = queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def account_config_snapshot(self) -> Any:
        return await self._serve(CONFIG)

    async def account_information_snapshot(self) -> Any:
        return await self._serve(INFORMATION)

    async def account_balances_snapshot(self) -> Any:
        return await self._serve(BALANCES)


def _fixture(name: str) -> Any:
    return json.loads((RECORDED_DEMO / name).read_text(encoding="utf-8"))


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class _FakeRest:
    """Serves one payload per SDK method name; ``on_call`` runs first on every call."""

    def __init__(self, payloads: dict[str, Any], on_call: Callable[[str], None] | None) -> None:
        self._payloads = payloads
        self._on_call = on_call
        self.called: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., _Response]:
        if name.startswith("_") or name not in self._payloads:
            raise AttributeError(name)

        def _call(*args: Any, **kwargs: Any) -> _Response:
            assert args == ()
            self.called.append(name)
            if self._on_call is not None:
                self._on_call(name)
            return _Response(self._payloads[name])

        return _call


def demo_sdk_payloads() -> dict[str, Any]:
    """The SDK models of the three recorded-Demo fixtures, keyed by SDK method name."""
    information = AccountInformationV3Response.from_dict(_fixture("account_information_v3.json"))
    balances = FuturesAccountBalanceV3Response.from_dict(_fixture("account_balance_v3.json"))
    config = FuturesAccountConfigurationResponse.from_dict(_fixture("account_config.json"))
    assert information is not None and balances is not None and config is not None
    return {
        "account_information_v3": information,
        "futures_account_balance_v3": balances,
        "futures_account_configuration": config,
    }


def build_demo_adapter(
    *,
    payloads: dict[str, Any] | None = None,
    on_sdk_call: Callable[[str], None] | None = None,
) -> tuple[BinanceUsdmAdapter, _FakeRest]:
    """The real adapter over a fake SDK; ``on_sdk_call(method_name)`` runs on each SDK call."""
    rest = _FakeRest(payloads if payloads is not None else demo_sdk_payloads(), on_sdk_call)
    gate = RestRateLimitGate(
        policy=test_only_signed_call_policy().rate_limit, clock=lambda: _GATE_START
    )
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        rest_gate=gate,
        signed_call_policy=test_only_signed_call_policy(),
    )
    return adapter, rest


async def demo_account_snapshots() -> tuple[
    AccountInformationSnapshot, tuple[AccountBalanceRow, ...], AccountConfigSnapshot
]:
    """(information, balances, config) read by the real adapter from the recorded fixtures."""
    adapter, _ = build_demo_adapter()
    return (
        await adapter.account_information_snapshot(),
        await adapter.account_balances_snapshot(),
        await adapter.account_config_snapshot(),
    )


__all__ = [
    "BALANCES",
    "CONFIG",
    "INFORMATION",
    "RECORDED_DEMO",
    "ScriptedAccountReader",
    "build_demo_adapter",
    "demo_account_snapshots",
    "demo_sdk_payloads",
]
