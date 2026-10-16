"""SDK-shaped fakes for the probe adapter tests (plan 18-12).

`FakeProbeRest` has one method per installed SDK REST method name the probe adapter calls.
Each records the keyword arguments it received (and the thread it ran on), then returns a
scripted payload wrapped like the SDK's `ApiResponse` (`.data()`), or raises a scripted
exception. Nothing here opens a connection, reads the environment or builds an SDK client.
`tests/test_binance_probe_contract.py` binds every recorded call against the installed SDK
method signature, so a fake that accepts a keyword the SDK does not would be caught there.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from src.adapters.binance_public import BinancePublicMarketData
from src.adapters.binance_ratelimit_gate import RestRateLimitGate

from tests.support.limits import test_only_rate_limit_policy

# The virtual clock's start; any timezone-aware instant works, the gate only compares.
TEST_ONLY_CLOCK_START = datetime(2026, 10, 16, 6, 0, 0, tzinfo=UTC)


class FakeResponse:
    """The `ApiResponse` surface the adapter reads: `data()`."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class FakeProbeRest:
    """Records every SDK call; answers from a per-method script (payload or exception)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.thread_ids: list[int] = []
        self._script: dict[str, list[object]] = {}

    def script(self, name: str, *outcomes: object) -> None:
        """Queue answers for `name`; an exception instance is raised, anything else returned."""
        self._script.setdefault(name, []).extend(outcomes)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def _answer(self, name: str, kwargs: dict[str, Any]) -> FakeResponse:
        self.calls.append((name, dict(kwargs)))
        self.thread_ids.append(threading.get_ident())
        queue = self._script.get(name)
        if not queue:
            raise AssertionError(f"unscripted SDK call: {name}")
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)

    # ----- queries (plan 18-12 Task 1) ----------------------------------- #

    def query_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("query_order", kwargs)

    def query_algo_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("query_algo_order", kwargs)

    # ----- placements and cancels (plan 18-12 Task 2) -------------------- #

    def new_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("new_order", kwargs)

    def new_algo_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("new_algo_order", kwargs)

    def cancel_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("cancel_order", kwargs)

    def cancel_algo_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("cancel_algo_order", kwargs)

    def cancel_all_open_orders(self, **kwargs: Any) -> FakeResponse:
        return self._answer("cancel_all_open_orders", kwargs)

    def cancel_all_algo_open_orders(self, **kwargs: Any) -> FakeResponse:
        return self._answer("cancel_all_algo_open_orders", kwargs)

    # ----- state capture (plan 18-12 Task 3) ----------------------------- #

    def current_all_open_orders(self, **kwargs: Any) -> FakeResponse:
        return self._answer("current_all_open_orders", kwargs)

    def current_all_algo_open_orders(self, **kwargs: Any) -> FakeResponse:
        return self._answer("current_all_algo_open_orders", kwargs)

    def position_information_v3(self, **kwargs: Any) -> FakeResponse:
        return self._answer("position_information_v3", kwargs)

    def account_trade_list(self, **kwargs: Any) -> FakeResponse:
        return self._answer("account_trade_list", kwargs)

    def futures_account_balance_v3(self, **kwargs: Any) -> FakeResponse:
        return self._answer("futures_account_balance_v3", kwargs)

    # ----- public reads, reached through BinancePublicMarketData --------- #

    def mark_price_kline_candlestick_data(self, **kwargs: Any) -> FakeResponse:
        return self._answer("mark_price_kline_candlestick_data", kwargs)

    def exchange_information(self, **kwargs: Any) -> FakeResponse:
        return self._answer("exchange_information", kwargs)


class FakeProbeSdk:
    """The `DerivativesTradingUsdsFutures` surface the adapter reads: `rest_api`."""

    def __init__(self, rest: FakeProbeRest | None = None) -> None:
        self.rest_api = rest if rest is not None else FakeProbeRest()


class VirtualClock:
    """A settable timezone-aware clock shared by the gate and the test."""

    def __init__(self, start: datetime = TEST_ONLY_CLOCK_START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def make_gate(clock: VirtualClock | None = None) -> RestRateLimitGate:
    """A gate holding the TEST_ONLY rate-limit policy and a virtual clock."""
    return RestRateLimitGate(
        policy=test_only_rate_limit_policy(),
        clock=clock if clock is not None else VirtualClock(),
    )


def make_public(rest: FakeProbeRest, gate: RestRateLimitGate) -> BinancePublicMarketData:
    """The real public reader over the fake REST object, holding `gate` (as plan 18-17 does)."""
    return BinancePublicMarketData(sdk_client=FakeProbeSdk(rest), rest_gate=gate)  # type: ignore[arg-type]


__all__ = [
    "TEST_ONLY_CLOCK_START",
    "FakeProbeRest",
    "FakeProbeSdk",
    "FakeResponse",
    "VirtualClock",
    "make_gate",
    "make_public",
]
