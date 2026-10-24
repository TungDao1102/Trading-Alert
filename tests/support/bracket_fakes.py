"""Shared fakes for the bracket cache (Phase 22, plan 22-12; plans 22-13 and 22-14 may reuse them).

* ``ScriptedBracketAdapter`` stands in for the adapter's ``leverage_brackets_snapshot``
  (``BracketPort``): per call it pops one scripted value, or raises a scripted exception, and
  records the symbol of every call. With ``virtual_time`` and ``advance_per_call`` the virtual
  clock moves during every call, so a read can take longer than the age bound.
* ``demo_table`` builds the adapter result type (``SymbolLeverageBrackets``) from the recorded
  Demo table (demo-observed, not mainnet) with a chosen notional coefficient, so a test never
  types a bracket value.
* ``build_bracket_adapter`` builds the real ``BinanceUsdmAdapter`` over a fake SDK serving the
  recorded ``leverage_brackets.json`` model; it is a local helper (it does not import the
  account fakes, which another plan of the same wave edits).

TEST_ONLY helpers; nothing here is a project value and no figure is a mainnet figure.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    NotionalAndLeverageBracketsResponse,
)
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    LeverageBracketRow,
    SymbolLeverageBrackets,
)

from tests.support.limits import test_only_signed_call_policy
from tests.support.phase22_fixtures import demo_brackets, load_leverage_brackets
from tests.support.virtual_time import VirtualTime

_GATE_START = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)
SDK_METHOD = "notional_and_leverage_brackets"


def demo_table(
    *, symbol: str = "BTCUSDT", notional_coef: Decimal | None = None
) -> SymbolLeverageBrackets:
    """The recorded Demo table as the adapter's result type (ten rows, response order)."""
    return SymbolLeverageBrackets(
        symbol=symbol,
        notional_coef=notional_coef,
        brackets=tuple(
            LeverageBracketRow(
                bracket=row.bracket,
                initial_leverage=row.initial_leverage,
                notional_floor=row.notional_floor,
                notional_cap=row.notional_cap,
                maint_margin_ratio=row.maint_margin_ratio,
                cum=row.cum,
            )
            for row in demo_brackets()
        ),
    )


class ScriptedBracketAdapter:
    """Scripted ``BracketPort``; ``responses`` are served in order, one per call."""

    def __init__(
        self,
        responses: list[object | BaseException],
        *,
        virtual_time: VirtualTime | None = None,
        advance_per_call: timedelta = timedelta(0),
        on_call: Callable[[str], None] | None = None,
    ) -> None:
        self._responses = list(responses)
        self._virtual_time = virtual_time
        self._advance = advance_per_call
        self._on_call = on_call
        self.calls: list[str] = []

    async def leverage_brackets_snapshot(self, *, symbol: str) -> Any:
        self.calls.append(symbol)
        if self._on_call is not None:
            self._on_call(symbol)
        if self._virtual_time is not None and self._advance > timedelta(0):
            await self._virtual_time.advance(self._advance.total_seconds())
        if not self._responses:
            raise AssertionError("no scripted response left for leverage_brackets_snapshot")
        value = self._responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class FakeBracketRest:
    """Serves the bracket model for ``notional_and_leverage_brackets``; ``on_call`` runs first."""

    def __init__(self, payload: Any, on_call: Callable[[str], None] | None) -> None:
        self._payload = payload
        self._on_call = on_call
        self.called: list[str] = []
        self.kwargs: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Callable[..., _Response]:
        if name != SDK_METHOD:
            raise AttributeError(name)

        def _call(*args: Any, **kwargs: Any) -> _Response:
            assert args == ()
            self.called.append(name)
            self.kwargs.append(dict(kwargs))
            if self._on_call is not None:
                self._on_call(name)
            return _Response(self._payload)

        return _call


def recorded_bracket_payload() -> Any:
    """The SDK oneOf wrapper built from the recorded Demo answer."""
    model = NotionalAndLeverageBracketsResponse.from_dict(load_leverage_brackets())
    assert model is not None
    return model


def build_bracket_adapter(
    *,
    payload: Any = None,
    on_sdk_call: Callable[[str], None] | None = None,
) -> tuple[BinanceUsdmAdapter, FakeBracketRest]:
    """The real adapter over a fake SDK; ``on_sdk_call(method_name)`` runs on each SDK call."""
    rest = FakeBracketRest(
        payload if payload is not None else recorded_bracket_payload(), on_sdk_call
    )
    gate = RestRateLimitGate(
        policy=test_only_signed_call_policy().rate_limit, clock=lambda: _GATE_START
    )
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        rest_gate=gate,
        signed_call_policy=test_only_signed_call_policy(),
    )
    return adapter, rest


__all__ = [
    "SDK_METHOD",
    "FakeBracketRest",
    "ScriptedBracketAdapter",
    "build_bracket_adapter",
    "demo_table",
    "recorded_bracket_payload",
]
