"""Fakes for the margin guard tests (Phase 22, plan 22-14; plan 22-15 reuses the rig).

* ``CompositeRest`` stands in for the SDK ``rest_api`` object of ONE real ``BinanceUsdmAdapter``.
  It serves the recorded Phase 21 account answers (accountConfig, account, balance), the stateful
  symbolConfig of plan 22-11 (CROSSED x20 and its two changes) and the recorded Phase 22 bracket
  table, by delegating to the fakes of the earlier plans (no payload table is repeated here). Every
  SDK call is recorded in one ordered list, may move the clock (``advance_per_call``) and may
  be made to fail (``fail``). All figures are Demo-recorded, demo-observed, not mainnet.
* ``build_rig`` builds the whole guard over that adapter: the real ``LiveEquitySource``,
  ``SymbolConfigGuard`` (target leverage 5) and ``BracketCache``, a scripted claims port, the same
  movable clock and the TEST_ONLY limits.
* ``account_payloads`` builds the three account SDK models from the recorded fixtures with a
  per-test edit applied to the JSON first.
* ``ScriptedAccount``, ``ScriptedConfigGuard``, ``ScriptedBrackets`` and ``ScriptedClaims`` stand in
  for the four ports of the guard directly; they share an event list so a test can prove which
  ports were reached and in what order.

TEST_ONLY helpers; nothing here is a project value.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
    AccountInformationV3Response,
    FuturesAccountBalanceV3Response,
    FuturesAccountConfigurationResponse,
)
from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import BinanceUsdmAdapter
from src.execution.account_equity import LiveEquitySource
from src.execution.bracket_cache import BracketCache, BracketReading
from src.execution.execution_limits import ExecutionLimits
from src.execution.margin_guard import MarginGuard, MarginGuardRequest
from src.execution.symbol_config_guard import ConfigGuardResult, SymbolConfigGuard
from src.risk.margin_check import AvailableMarginCheck, MarginClaim

from tests.support.account_fakes import _FakeRest, _fixture
from tests.support.bracket_fakes import FakeBracketRest, recorded_bracket_payload
from tests.support.config_guard_fakes import StatefulConfigSdk
from tests.support.execution_limits import test_only_execution_limits
from tests.support.limits import test_only_signed_call_policy

START = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
QUOTE_ASSET = "USDT"
SYMBOL = "BTCUSDT"
TARGET_LEVERAGE = 5  # TEST_ONLY composition value (D035 cap), passed to the real config guard

ACCOUNT_CONFIG_READ = "futures_account_configuration"
ACCOUNT_INFORMATION_READ = "account_information_v3"
ACCOUNT_BALANCE_READ = "futures_account_balance_v3"
CONFIG_READ = "symbol_configuration"
MARGIN_POST = "change_margin_type"
LEVERAGE_POST = "change_initial_leverage"
BRACKET_READ = "notional_and_leverage_brackets"


class MovingClock:
    """A plain mutable clock; ``advance`` moves it and may go backwards (a negative delta)."""

    def __init__(self, start: datetime = START) -> None:
        self.value = start
        self.reads = 0

    def __call__(self) -> datetime:
        self.reads += 1
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def request(**overrides: Any) -> MarginGuardRequest:
    """The plan of the worked numbers: LONG 0.01 at 80000, stop 66000, mark 80000, rates 0.0004."""
    fields: dict[str, Any] = {
        "trade_plan_id": "P1",
        "symbol": SYMBOL,
        "side": "LONG",
        "quantity": Decimal("0.01"),
        "limit_price": Decimal("80000"),
        "stop_price": Decimal("66000"),
        "mark_price": Decimal("80000"),
        "fee_rate_entry": Decimal("0.0004"),
        "fee_rate_exit": Decimal("0.0004"),
        "symbol_is_flat": True,
    }
    fields.update(overrides)
    return MarginGuardRequest(**fields)


def account_payloads(
    *,
    config_edit: Callable[[dict[str, Any]], None] | None = None,
    information_edit: Callable[[dict[str, Any]], None] | None = None,
    balance_edit: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    """The three account SDK models from the recorded fixtures, each JSON edited first."""
    config = copy.deepcopy(_fixture("account_config.json"))
    information = copy.deepcopy(_fixture("account_information_v3.json"))
    balances = copy.deepcopy(_fixture("account_balance_v3.json"))
    if config_edit is not None:
        config_edit(config)
    if information_edit is not None:
        information_edit(information)
    if balance_edit is not None:
        balance_edit(balances)
    models = (
        FuturesAccountConfigurationResponse.from_dict(config),
        AccountInformationV3Response.from_dict(information),
        FuturesAccountBalanceV3Response.from_dict(balances),
    )
    assert all(model is not None for model in models)
    return {
        ACCOUNT_CONFIG_READ: models[0],
        ACCOUNT_INFORMATION_READ: models[1],
        ACCOUNT_BALANCE_READ: models[2],
    }


def set_available_balance(value: str) -> Callable[[dict[str, Any]], None]:
    """An information edit: the top-level and the quote row's availableBalance (kept equal)."""

    def edit(information: dict[str, Any]) -> None:
        information["availableBalance"] = value
        for row in information["assets"]:
            if row["asset"] == QUOTE_ASSET:
                row["availableBalance"] = value

    return edit


class CompositeRest:
    """One SDK stand-in serving the account, configuration and bracket answers; see the module."""

    def __init__(
        self,
        *,
        clock: MovingClock | None = None,
        advance_per_call: timedelta = timedelta(0),
        config_sdk: StatefulConfigSdk | None = None,
        account: dict[str, Any] | None = None,
        bracket_payload: Any = None,
    ) -> None:
        self._clock = clock
        self._advance = advance_per_call
        self._account = _FakeRest(account if account is not None else account_payloads(), None)
        self.config_sdk = (
            config_sdk if config_sdk is not None else StatefulConfigSdk.from_recorded()
        )
        self._brackets = FakeBracketRest(
            bracket_payload if bracket_payload is not None else recorded_bracket_payload(), None
        )
        self.calls: list[str] = []
        self.fail: dict[str, BaseException] = {}

    def count(self, name: str) -> int:
        return self.calls.count(name)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)
        for target in (self._account, self.config_sdk, self._brackets):
            try:
                method = getattr(target, name)
            except AttributeError:
                continue
            return self._wrap(name, method)
        raise AttributeError(name)

    def _wrap(self, name: str, method: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            if self._clock is not None and self._advance != timedelta(0):
                self._clock.advance(self._advance)
            failure = self.fail.get(name)
            if failure is not None:
                raise failure
            return method(*args, **kwargs)

        return call


class ScriptedClaims:
    """A claims port returning a fixed list (or raising); records every call."""

    def __init__(
        self,
        claims: Sequence[MarginClaim] = (),
        *,
        exception: BaseException | None = None,
        events: list[str] | None = None,
        awaitable: bool = False,
    ) -> None:
        self._claims = tuple(claims)
        self._exception = exception
        self._events = events
        self._awaitable = awaitable
        self.calls = 0

    def list_margin_claims(self) -> Any:
        self.calls += 1
        if self._events is not None:
            self._events.append("claims")
        if self._exception is not None:
            raise self._exception
        if self._awaitable:
            return self._later()
        return list(self._claims)

    async def _later(self) -> list[MarginClaim]:
        return list(self._claims)


@dataclass
class GuardRig:
    """The guard over the real adapter and its parts, for the end-to-end tests."""

    guard: MarginGuard
    rest: CompositeRest
    clock: MovingClock
    claims: ScriptedClaims
    equity: LiveEquitySource
    brackets: BracketCache
    config_guard: SymbolConfigGuard
    limits: ExecutionLimits
    extras: dict[str, Any] = field(default_factory=dict)


def build_rig(
    *,
    claims: Sequence[MarginClaim] = (),
    claims_exception: BaseException | None = None,
    limits: ExecutionLimits | None = None,
    advance_per_call: timedelta = timedelta(0),
    config_sdk: StatefulConfigSdk | None = None,
    account: dict[str, Any] | None = None,
    bracket_payload: Any = None,
    target_leverage: int = TARGET_LEVERAGE,
) -> GuardRig:
    """The whole guard over one real adapter served by ``CompositeRest`` (TEST_ONLY limits)."""
    clock = MovingClock()
    rest = CompositeRest(
        clock=clock,
        advance_per_call=advance_per_call,
        config_sdk=config_sdk,
        account=account,
        bracket_payload=bracket_payload,
    )
    gate = RestRateLimitGate(policy=test_only_signed_call_policy().rate_limit, clock=lambda: START)
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        rest_gate=gate,
        signed_call_policy=test_only_signed_call_policy(),
    )
    the_limits = limits if limits is not None else test_only_execution_limits()
    equity = LiveEquitySource(
        adapter=adapter, clock=clock, limits=the_limits, quote_asset=QUOTE_ASSET
    )
    brackets = BracketCache(adapter=adapter, clock=clock, limits=the_limits)
    config_guard = SymbolConfigGuard(adapter=adapter, target_leverage=target_leverage)
    scripted_claims = ScriptedClaims(claims, exception=claims_exception)
    guard = MarginGuard(
        config_guard=config_guard,
        brackets=brackets,
        account=equity,
        claims=scripted_claims,
        clock=clock,
        limits=the_limits,
    )
    return GuardRig(
        guard=guard,
        rest=rest,
        clock=clock,
        claims=scripted_claims,
        equity=equity,
        brackets=brackets,
        config_guard=config_guard,
        limits=the_limits,
    )


# ------------------------------------------------------------------------ scripted ports


class ScriptedAccount:
    """A ``MarginAccountPort`` answering a fixed ``AvailableMarginCheck`` (or raising)."""

    def __init__(
        self,
        check: AvailableMarginCheck | object,
        *,
        events: list[str] | None = None,
        refresh_exception: BaseException | None = None,
        check_exception: BaseException | None = None,
        on_check: Callable[[], None] | None = None,
    ) -> None:
        self._check = check
        self._events = events if events is not None else []
        self._refresh_exception = refresh_exception
        self._check_exception = check_exception
        self._on_check = on_check
        self.refreshes = 0
        self.check_times: list[datetime] = []

    async def refresh(self) -> None:
        self.refreshes += 1
        self._events.append("refresh")
        if self._refresh_exception is not None:
            raise self._refresh_exception

    def check_margin(self, *, now_utc: datetime) -> Any:
        self._events.append("check_margin")
        self.check_times.append(now_utc)
        if self._on_check is not None:
            self._on_check()
        if self._check_exception is not None:
            raise self._check_exception
        return self._check


class ScriptedConfigGuard:
    """A ``ConfigGuardPort`` answering a fixed result (or raising)."""

    def __init__(
        self,
        result: ConfigGuardResult | object,
        *,
        events: list[str] | None = None,
        exception: BaseException | None = None,
        target_leverage: int = TARGET_LEVERAGE,
    ) -> None:
        self._result = result
        self._events = events if events is not None else []
        self._exception = exception
        self.target_leverage = target_leverage
        self.calls: list[tuple[str, bool]] = []

    async def ensure(self, *, symbol: str, symbol_is_flat: bool) -> Any:
        self.calls.append((symbol, symbol_is_flat))
        self._events.append("config")
        if self._exception is not None:
            raise self._exception
        return self._result


class ScriptedBrackets:
    """A ``BracketPort`` answering a fixed reading, None, or raising; records every call."""

    def __init__(
        self,
        reading: BracketReading | None | object,
        *,
        events: list[str] | None = None,
        exception: BaseException | None = None,
        on_get: Callable[[], None] | None = None,
    ) -> None:
        self._reading = reading
        self._events = events if events is not None else []
        self._exception = exception
        self._on_get = on_get
        self.calls: list[str] = []

    async def get(self, *, symbol: str) -> Any:
        self.calls.append(symbol)
        self._events.append("brackets")
        if self._on_get is not None:
            self._on_get()
        if self._exception is not None:
            raise self._exception
        return self._reading


def config_result(**overrides: Any) -> ConfigGuardResult:
    """A passing configuration result (ISOLATED x5, no POST sent); override any field."""
    fields: dict[str, Any] = {
        "ok": True,
        "reason_code": "OK",
        "alert_reason": None,
        "margin_type": "ISOLATED",
        "leverage": TARGET_LEVERAGE,
        "max_notional_value": Decimal("100000000"),
        "changed": False,
        "previous_margin_type": "ISOLATED",
        "previous_leverage": TARGET_LEVERAGE,
        "posts_sent": 0,
    }
    fields.update(overrides)
    return ConfigGuardResult(**fields)


def margin_check(
    *, available: str = "4999.09343961", equity: str = "4999.09343961", at: datetime = START
) -> AvailableMarginCheck:
    """A usable account judgement."""
    return AvailableMarginCheck(
        available=Decimal(available),
        equity=Decimal(equity),
        observed_at_utc=at,
        reason_code="OK",
        blocked=None,
    )


def refused_check(blocked: str) -> AvailableMarginCheck:
    """A refused account judgement with the given plain ``blocked`` value."""
    return AvailableMarginCheck(
        available=None,
        equity=None,
        observed_at_utc=None,
        reason_code="UNCERTAIN_ACCOUNT_STATE",
        blocked=blocked,
    )


__all__ = [
    "ACCOUNT_BALANCE_READ",
    "ACCOUNT_CONFIG_READ",
    "ACCOUNT_INFORMATION_READ",
    "BRACKET_READ",
    "CONFIG_READ",
    "LEVERAGE_POST",
    "MARGIN_POST",
    "QUOTE_ASSET",
    "START",
    "SYMBOL",
    "TARGET_LEVERAGE",
    "CompositeRest",
    "GuardRig",
    "MovingClock",
    "ScriptedAccount",
    "ScriptedBrackets",
    "ScriptedClaims",
    "ScriptedConfigGuard",
    "account_payloads",
    "build_rig",
    "config_result",
    "margin_check",
    "refused_check",
    "request",
    "set_available_balance",
]
