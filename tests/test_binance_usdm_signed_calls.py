"""Signed calls of BinanceUsdmAdapter: explicit recvWindow, fail closed, -1021, gate (plan 18-13).

* every signed SDK call carries `recv_window` equal to the ratified `SignedCallPolicy` value;
  an adapter without a policy refuses a signed call before the gate and before the SDK;
* a signed policy requires the one process-wide `RestRateLimitGate` whose policy equals
  `signed_call_policy.rate_limit`; a drift guard requires a clock;
* a 418 bans and a 429 pauses the shared gate (the TEST_ONLY fallbacks are distinct, so a
  swapped fallback fails); nothing is retried because of a 418 or a 429 (user record
  18-DEC-O-18-01.md and its amendment of 2026-10-16);
* a -1021 (CLOCK_SKEW) answer calls the optional hook once and re-raises the same exception;
  it is never retried.

Numbers come from the TEST_ONLY objects of `tests/support/limits.py`; no test sleeps.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from binance_common.errors import (
    BadRequestError,
    RateLimitBanError,
    TooManyRequestsError,
)
from src.adapters.binance_clock import (
    ClockDriftGuard,
    DriftBlockReason,
    DriftVerdict,
    evaluate_clock_drift,
    measure_clock_drift,
)
from src.adapters.binance_limits import RateLimitPolicy, SignedCallPolicy
from src.adapters.binance_ratelimit_gate import (
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    RateLimitBanActive,
    RateLimitPauseActive,
    RestGateRefusal,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import (
    BinanceUsdmAdapter,
    EntriesBlocked,
    SignedCallPolicyMissing,
)
from src.domain.exchange_errors import ExchangeErrorCategory
from structlog.testing import capture_logs

from tests.support.intent_store_fakes import InMemoryExecutionIntentStore
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_418_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_418,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_429_NO_RETRY_AFTER_WAIT_SECONDS as WAIT_429,
)
from tests.support.limits import (
    TEST_ONLY_RATE_LIMIT_RETRY_AFTER_CAP_SECONDS as CAP,
)
from tests.support.limits import (
    TEST_ONLY_RECV_WINDOW_MS as RECV_WINDOW,
)
from tests.support.limits import (
    test_only_drift_limits,
    test_only_signed_call_policy,
)

START = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
UPDATE_MS = 1_791_360_000_000
ENTRY_ID = "e" * 36
ALGO_ID = "a" * 36


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("a real asyncio.sleep was called")

    monkeypatch.setattr(asyncio, "sleep", _forbidden)


class VirtualClock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class RecordingSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


class RecordingHook:
    def __init__(self, error: BaseException | None = None) -> None:
        self.calls = 0
        self._error = error

    def __call__(self) -> None:
        self.calls += 1
        if self._error is not None:
            raise self._error


# --------------------------------------------------------------------------- #
# SDK-shaped fake: records every call with its args and kwargs.
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


def _payloads(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_all_open_orders": [],
        "current_all_algo_open_orders": [],
        "position_information_v3": [],
        "query_algo_order": SimpleNamespace(algo_status="NEW", update_time=UPDATE_MS),
        "query_order": SimpleNamespace(order_id=1, status="NEW", update_time=UPDATE_MS),
        "cancel_order": SimpleNamespace(),
        "cancel_algo_order": SimpleNamespace(),
        "new_order": SimpleNamespace(
            symbol=kwargs.get("symbol"),
            client_order_id=kwargs.get("new_client_order_id"),
            order_id=11,
            side="BUY",
            position_side="BOTH",
            type="LIMIT",
            time_in_force="GTC",
            status="NEW",
            orig_qty="0.010",
            price="100.0",
            update_time=UPDATE_MS,
        ),
        "new_algo_order": SimpleNamespace(
            symbol=kwargs.get("symbol"),
            client_algo_id=kwargs.get("client_algo_id"),
            algo_id=22,
            algo_type="CONDITIONAL",
            order_type="STOP_MARKET",
            side="SELL",
            position_side="BOTH",
            algo_status="NEW",
            trigger_price="98.0",
            close_position=True,
            working_type="MARK_PRICE",
            update_time=UPDATE_MS,
        ),
        "get_current_position_mode": SimpleNamespace(dual_side_position=False),
        "user_commission_rate": SimpleNamespace(
            symbol="BTCUSDT", maker_commission_rate="0.0002", taker_commission_rate="0.0004"
        ),
        "account_information_v3": SimpleNamespace(
            total_margin_balance="1",
            total_wallet_balance="1",
            total_unrealized_profit="0",
            assets=[
                SimpleNamespace(
                    asset="USDT", wallet_balance="1", unrealized_profit="0", margin_balance="1"
                )
            ],
        ),
        "futures_account_balance_v3": [
            SimpleNamespace(asset="USDT", balance="1", cross_un_pnl="0")
        ],
        "futures_account_configuration": SimpleNamespace(
            multi_assets_margin=False, dual_side_position=False
        ),
        "symbol_configuration": [
            SimpleNamespace(
                symbol="BTCUSDT",
                margin_type="CROSSED",
                leverage=20,
                is_auto_add_margin=False,
                max_notional_value="20000000",
            )
        ],
        "notional_and_leverage_brackets": [
            SimpleNamespace(
                symbol="BTCUSDT",
                notional_coef=None,
                brackets=[
                    SimpleNamespace(
                        bracket=1,
                        initial_leverage=125,
                        notional_floor=0,
                        notional_cap=50000,
                        maint_margin_ratio=0.004,
                        cum=0.0,
                    )
                ],
            )
        ],
        "change_margin_type": SimpleNamespace(code=200, msg="success"),
        "account_trade_list": [],
        "get_income_history": [],
        "kline_candlestick_data": [],
        "mark_price_kline_candlestick_data": [],
        "open_interest": SimpleNamespace(symbol="BTCUSDT", time=UPDATE_MS, open_interest="1"),
        "open_interest_statistics": [],
        "get_funding_rate_history": [],
        "check_server_time": SimpleNamespace(server_time=UPDATE_MS),
        "exchange_information": SimpleNamespace(symbols=[]),
    }


SDK_NAMES = frozenset(_payloads({}))


class RecordingRest:
    """Each SDK REST method records its args and kwargs and raises the next scripted error.

    `absent` names SDK methods that answer every call with -2013 (order does not exist).
    `absent_after` names SDK methods that answer normally for that many calls and then -2013.
    `side_effects` runs once, inside the next call of the named method, before it answers.
    """

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.kwargs: dict[str, list[dict[str, Any]]] = {}
        self.args: dict[str, list[tuple[Any, ...]]] = {}
        self.script: dict[str, list[BaseException]] = {}
        self.absent: set[str] = set()
        self.absent_after: dict[str, int] = {}
        self.side_effects: dict[str, Callable[[], None]] = {}

    def fail(self, name: str, *excs: BaseException) -> None:
        self.script.setdefault(name, []).extend(excs)

    def total(self) -> int:
        return sum(self.calls.values())

    def __getattr__(self, name: str) -> Any:
        if name not in SDK_NAMES:
            raise AttributeError(name)

        def _call(*args: Any, **kwargs: Any) -> _Response:
            self.calls[name] += 1
            self.kwargs.setdefault(name, []).append(dict(kwargs))
            self.args.setdefault(name, []).append(args)
            effect = self.side_effects.pop(name, None)
            if effect is not None:
                effect()
            queue = self.script.get(name)
            if queue:
                raise queue.pop(0)
            if name in self.absent or self.calls[name] > self.absent_after.get(name, 1 << 30):
                raise BadRequestError("Order does not exist.", -2013)
            return _Response(_payloads(kwargs)[name])

        return _call


def _gate(clock: VirtualClock) -> RestRateLimitGate:
    return RestRateLimitGate(policy=test_only_signed_call_policy().rate_limit, clock=clock)


def _adapter(
    *,
    clock: VirtualClock | None = None,
    gate: RestRateLimitGate | None = None,
    policy: SignedCallPolicy | None | str = "test_only",
    drift_guard: ClockDriftGuard | None = None,
    on_clock_skew: Callable[[], None] | None = None,
) -> tuple[BinanceUsdmAdapter, RecordingRest, RecordingSleep, RestRateLimitGate | None]:
    """A real adapter over the recording fake; by default with the TEST_ONLY policy and a gate."""
    clock = clock if clock is not None else VirtualClock()
    signed = test_only_signed_call_policy() if policy == "test_only" else policy
    assert signed is None or isinstance(signed, SignedCallPolicy)
    if gate is None and signed is not None:
        gate = _gate(clock)
    rest = RecordingRest()
    sleep = RecordingSleep()
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        rest_gate=gate,
        sleep=sleep,
        signed_call_policy=signed,
        drift_guard=drift_guard,
        clock=clock if drift_guard is not None else None,
        on_clock_skew=on_clock_skew,
    )
    return adapter, rest, sleep, gate


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _query_order(a: BinanceUsdmAdapter) -> Any:
    return a.query_order_by_client(symbol="BTCUSDT", orig_client_order_id=ENTRY_ID)


def _place_entry(a: BinanceUsdmAdapter) -> Any:
    return a.place_entry(
        symbol="BTCUSDT",
        side="BUY",
        position_side="BOTH",
        time_in_force="GTC",
        quantity=Decimal("0.010"),
        price=Decimal("100.0"),
        new_client_order_id=ENTRY_ID,
    )


TRACER_METHODS: dict[str, tuple[Callable[[BinanceUsdmAdapter], Any], str]] = {
    "query_order_by_client": (_query_order, "query_order"),
    "place_entry": (_place_entry, "new_order"),
}
TRACER_NAMES = sorted(TRACER_METHODS)


# --------------------------------------------------------------------------- #
# Task 1 (tracer): recv_window on a query and a placement.
# --------------------------------------------------------------------------- #


def test_query_order_by_client_passes_the_ratified_recv_window() -> None:
    adapter, rest, sleep, _ = _adapter()
    probe = _run(_query_order(adapter))
    assert probe.found is True
    assert rest.calls["query_order"] == 1
    assert rest.kwargs["query_order"][0]["recv_window"] == RECV_WINDOW
    assert rest.kwargs["query_order"][0]["recv_window"] == (
        test_only_signed_call_policy().recv_window_ms
    )
    assert rest.args["query_order"] == [()]
    assert sleep.waits == []


def test_place_entry_passes_the_ratified_recv_window() -> None:
    adapter, rest, sleep, _ = _adapter()
    result = _run(_place_entry(adapter))
    assert result.client_order_id == ENTRY_ID
    assert rest.calls["new_order"] == 1
    assert rest.kwargs["new_order"][0]["recv_window"] == RECV_WINDOW
    assert rest.args["new_order"] == [()]
    assert sleep.waits == []


def test_the_recv_window_is_the_policy_value_not_a_constant() -> None:
    policy = SignedCallPolicy(
        recv_window_ms=RECV_WINDOW + 7, rate_limit=test_only_signed_call_policy().rate_limit
    )
    adapter, rest, _, _ = _adapter(policy=policy)
    _run(_query_order(adapter))
    _run(_place_entry(adapter))
    assert rest.kwargs["query_order"][0]["recv_window"] == RECV_WINDOW + 7
    assert rest.kwargs["new_order"][0]["recv_window"] == RECV_WINDOW + 7


# --------------------------------------------------------------------------- #
# Fail closed without a policy.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", TRACER_NAMES)
@pytest.mark.parametrize("restricted", [False, True], ids=["open_gate", "paused_gate"])
def test_tracer_method_without_a_policy_fails_closed_before_gate_and_sdk(
    method: str, restricted: bool
) -> None:
    clock = VirtualClock()
    gate = _gate(clock)
    if restricted:
        gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    adapter, rest, sleep, _ = _adapter(clock=clock, gate=gate, policy=None)
    call, _ = TRACER_METHODS[method]
    with pytest.raises(SignedCallPolicyMissing):
        _run(call(adapter))
    assert rest.total() == 0
    assert sleep.waits == []


def test_bare_adapter_without_a_policy_fails_closed() -> None:
    rest = RecordingRest()
    adapter = BinanceUsdmAdapter(SimpleNamespace(rest_api=rest))  # type: ignore[arg-type]
    for name in TRACER_NAMES:
        call, _ = TRACER_METHODS[name]
        with pytest.raises(SignedCallPolicyMissing):
            _run(call(adapter))
    assert rest.total() == 0


def test_public_methods_ignore_a_missing_policy_but_keep_the_gate() -> None:
    clock = VirtualClock()
    gate = _gate(clock)
    adapter, rest, _, _ = _adapter(clock=clock, gate=gate, policy=None)
    _run(adapter.server_time())
    _run(adapter.klines("BTCUSDT", "1h"))
    _run(adapter.exchange_info())
    assert rest.calls["check_server_time"] == 1
    assert "recv_window" not in rest.kwargs["check_server_time"][0]
    assert "recv_window" not in rest.kwargs["kline_candlestick_data"][0]
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)
    before = rest.total()
    with pytest.raises(RateLimitPauseActive):
        _run(adapter.server_time())
    with pytest.raises(RateLimitPauseActive):
        _run(adapter.klines("BTCUSDT", "1h"))
    assert rest.total() == before


# --------------------------------------------------------------------------- #
# Construction checks.
# --------------------------------------------------------------------------- #


def test_a_policy_without_a_gate_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="rest_gate"):
        BinanceUsdmAdapter(
            sdk_client=SimpleNamespace(rest_api=RecordingRest()),  # type: ignore[arg-type]
            signed_call_policy=test_only_signed_call_policy(),
        )


def test_a_gate_whose_policy_differs_is_refused_at_construction() -> None:
    policy = test_only_signed_call_policy()
    other = RateLimitPolicy(
        no_retry_after_wait_418_seconds=WAIT_418,
        no_retry_after_wait_429_seconds=WAIT_429 + 1,
        retry_after_cap_seconds=CAP,
    )
    gate = RestRateLimitGate(policy=other, clock=VirtualClock())
    with pytest.raises(ValueError, match="rate_limit"):
        BinanceUsdmAdapter(
            sdk_client=SimpleNamespace(rest_api=RecordingRest()),  # type: ignore[arg-type]
            signed_call_policy=policy,
            rest_gate=gate,
        )


def test_a_drift_guard_without_a_clock_is_refused_at_construction() -> None:
    clock = VirtualClock()
    with pytest.raises(ValueError, match="clock"):
        BinanceUsdmAdapter(
            sdk_client=SimpleNamespace(rest_api=RecordingRest()),  # type: ignore[arg-type]
            signed_call_policy=test_only_signed_call_policy(),
            rest_gate=_gate(clock),
            drift_guard=ClockDriftGuard(limits=test_only_drift_limits()),
        )


# --------------------------------------------------------------------------- #
# A 418 bans and a 429 pauses the shared gate through the helper (distinct fallbacks).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", TRACER_NAMES)
@pytest.mark.parametrize(
    ("make", "reason", "expected"),
    [
        (lambda: RateLimitBanError("banned", -1003, None), IP_BAN_418, WAIT_418),
        (lambda: TooManyRequestsError("slow down", -1003, None), RATE_LIMIT_PAUSE_429, WAIT_429),
    ],
    ids=["418", "429"],
)
def test_rate_limit_without_retry_after_sets_the_policy_fallback(
    method: str, make: Callable[[], BaseException], reason: str, expected: int
) -> None:
    adapter, rest, sleep, gate = _adapter()
    assert gate is not None
    call, sdk_name = TRACER_METHODS[method]
    exc = make()
    rest.fail(sdk_name, exc)
    with pytest.raises(type(exc)) as info:
        _run(call(adapter))
    assert info.value is exc
    assert rest.calls[sdk_name] == 1
    assert sleep.waits == []
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.reason == reason
    assert restriction.remaining_seconds == expected


# --------------------------------------------------------------------------- #
# -1021 (CLOCK_SKEW): the hook once, the same exception, no retry.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", TRACER_NAMES)
def test_clock_skew_calls_the_hook_once_and_is_not_retried(method: str) -> None:
    hook = RecordingHook()
    adapter, rest, sleep, gate = _adapter(on_clock_skew=hook)
    assert gate is not None
    call, sdk_name = TRACER_METHODS[method]
    skew = BadRequestError("Timestamp for this request is outside of the recvWindow.", -1021)
    rest.fail(sdk_name, skew, BadRequestError("again", -1021))
    with pytest.raises(BadRequestError) as info:
        _run(call(adapter))
    assert info.value is skew
    assert hook.calls == 1
    assert rest.calls[sdk_name] == 1
    assert rest.total() == 1
    assert sleep.waits == []
    assert gate.restriction() is None


@pytest.mark.parametrize("method", TRACER_NAMES)
def test_clock_skew_without_a_hook_re_raises(method: str) -> None:
    adapter, rest, _, _ = _adapter()
    call, sdk_name = TRACER_METHODS[method]
    skew = BadRequestError("skew", -1021)
    rest.fail(sdk_name, skew)
    with pytest.raises(BadRequestError) as info:
        _run(call(adapter))
    assert info.value is skew
    assert rest.calls[sdk_name] == 1


@pytest.mark.parametrize("method", TRACER_NAMES)
def test_a_failing_hook_is_logged_and_does_not_replace_the_original(method: str) -> None:
    hook = RecordingHook(error=RuntimeError("hook exploded with secret-ish text"))
    adapter, rest, _, _ = _adapter(on_clock_skew=hook)
    call, sdk_name = TRACER_METHODS[method]
    skew = BadRequestError("skew", -1021)
    rest.fail(sdk_name, skew)
    with capture_logs() as logs:
        with pytest.raises(BadRequestError) as info:
            _run(call(adapter))
    assert info.value is skew
    assert hook.calls == 1
    assert rest.calls[sdk_name] == 1
    failures = [entry for entry in logs if entry["event"].endswith("on_clock_skew_failed")]
    assert len(failures) == 1
    assert failures[0]["error_class"] == "RuntimeError"
    assert "secret-ish" not in repr(failures[0])


@pytest.mark.parametrize("method", TRACER_NAMES)
def test_other_errors_do_not_call_the_clock_skew_hook(method: str) -> None:
    hook = RecordingHook()
    adapter, rest, _, _ = _adapter(on_clock_skew=hook)
    call, sdk_name = TRACER_METHODS[method]
    rest.fail(sdk_name, BadRequestError("rejected", -2010))
    with pytest.raises(BadRequestError):
        _run(call(adapter))
    assert hook.calls == 0


# =========================================================================== #
# Task 2: every signed method, entries blocked, SDK parameter names.
# =========================================================================== #


def _protective(a: BinanceUsdmAdapter) -> Any:
    return a.place_algo_protective(
        symbol="BTCUSDT",
        side="SELL",
        algo_type="CONDITIONAL",
        type="STOP_MARKET",
        position_side="BOTH",
        trigger_price=Decimal("98.0"),
        close_position=True,
        quantity=None,
        working_type="MARK_PRICE",
        client_algo_id=ALGO_ID,
    )


# The eighteen signed methods and the SDK method each calls (plan 21-03 added three, 21-08 two,
# plan 22-01 the two configuration reads; plan 22-06 takes the registry to twenty).
SIGNED: dict[str, tuple[Callable[[BinanceUsdmAdapter], Any], str]] = {
    "snapshot_open_normal_orders": (
        lambda a: a.snapshot_open_normal_orders(symbol="BTCUSDT"),
        "current_all_open_orders",
    ),
    "snapshot_open_algo_orders": (
        lambda a: a.snapshot_open_algo_orders(symbol="BTCUSDT"),
        "current_all_algo_open_orders",
    ),
    "snapshot_positions": (
        lambda a: a.snapshot_positions(symbol="BTCUSDT"),
        "position_information_v3",
    ),
    "query_algo_order_by_client": (
        lambda a: a.query_algo_order_by_client(client_algo_id=ALGO_ID),
        "query_algo_order",
    ),
    "query_order_by_client": (_query_order, "query_order"),
    "cancel_normal_order": (
        lambda a: a.cancel_normal_order(symbol="BTCUSDT", orig_client_order_id=ENTRY_ID),
        "cancel_order",
    ),
    "cancel_algo_order": (
        lambda a: a.cancel_algo_order(symbol="BTCUSDT", client_algo_id=ALGO_ID),
        "cancel_algo_order",
    ),
    "place_entry": (_place_entry, "new_order"),
    "place_algo_protective": (_protective, "new_algo_order"),
    "get_position_mode": (lambda a: a.get_position_mode(), "get_current_position_mode"),
    "user_commission_rate": (lambda a: a.user_commission_rate("BTCUSDT"), "user_commission_rate"),
    "account_information_snapshot": (
        lambda a: a.account_information_snapshot(),
        "account_information_v3",
    ),
    "account_balances_snapshot": (
        lambda a: a.account_balances_snapshot(),
        "futures_account_balance_v3",
    ),
    "account_config_snapshot": (
        lambda a: a.account_config_snapshot(),
        "futures_account_configuration",
    ),
    "symbol_config_snapshot": (
        lambda a: a.symbol_config_snapshot(symbol="BTCUSDT"),
        "symbol_configuration",
    ),
    "leverage_brackets_snapshot": (
        lambda a: a.leverage_brackets_snapshot(symbol="BTCUSDT"),
        "notional_and_leverage_brackets",
    ),
    "change_margin_type": (
        lambda a: a.change_margin_type(symbol="BTCUSDT", margin_type="ISOLATED"),
        "change_margin_type",
    ),
    "user_trades_in_window": (
        lambda a: a.user_trades_in_window(
            symbol="BTCUSDT",
            start_utc=datetime(2026, 10, 22, tzinfo=UTC),
            end_utc=datetime(2026, 10, 22, 12, tzinfo=UTC),
        ),
        "account_trade_list",
    ),
    "income_in_window": (
        lambda a: a.income_in_window(
            income_type="FUNDING_FEE",
            start_utc=datetime(2026, 10, 22, tzinfo=UTC),
            end_utc=datetime(2026, 10, 22, 12, tzinfo=UTC),
        ),
        "get_income_history",
    ),
}
SIGNED_NAMES = sorted(SIGNED)

_P = "POSITIONAL_OR_KEYWORD"
_K = "KEYWORD_ONLY"

# Public signatures before plan 18-13 (parameter name, kind): the refactor keeps them.
SIGNATURE_SNAPSHOTS: dict[str, tuple[tuple[str, str], ...]] = {
    "snapshot_open_normal_orders": (("self", _P), ("symbol", _K)),
    "snapshot_open_algo_orders": (("self", _P), ("symbol", _K)),
    "snapshot_positions": (("self", _P), ("symbol", _K)),
    "query_algo_order_by_client": (("self", _P), ("client_algo_id", _K)),
    "query_order_by_client": (("self", _P), ("symbol", _K), ("orig_client_order_id", _K)),
    "cancel_normal_order": (("self", _P), ("symbol", _K), ("orig_client_order_id", _K)),
    "cancel_algo_order": (("self", _P), ("symbol", _K), ("client_algo_id", _K)),
    "place_entry": (
        ("self", _P),
        ("symbol", _K),
        ("side", _K),
        ("position_side", _K),
        ("time_in_force", _K),
        ("quantity", _K),
        ("price", _K),
        ("new_client_order_id", _K),
        ("good_till_date", _K),
    ),
    "place_algo_protective": (
        ("self", _P),
        ("symbol", _K),
        ("side", _K),
        ("algo_type", _K),
        ("type", _K),
        ("position_side", _K),
        ("trigger_price", _K),
        ("close_position", _K),
        ("quantity", _K),
        ("working_type", _K),
        ("client_algo_id", _K),
        ("reduce_only", _K),
    ),
    "get_position_mode": (("self", _P),),
    "user_commission_rate": (("self", _P), ("symbol", _P)),
    "account_information_snapshot": (("self", _P),),
    "account_balances_snapshot": (("self", _P),),
    "account_config_snapshot": (("self", _P),),
    "symbol_config_snapshot": (("self", _P), ("symbol", _K)),
    "leverage_brackets_snapshot": (("self", _P), ("symbol", _K)),
    "change_margin_type": (("self", _P), ("symbol", _K), ("margin_type", _K)),
    "user_trades_in_window": (("self", _P), ("symbol", _K), ("start_utc", _K), ("end_utc", _K)),
    "income_in_window": (("self", _P), ("income_type", _K), ("start_utc", _K), ("end_utc", _K)),
}


def test_the_signed_set_is_the_eighteen_methods() -> None:
    assert len(SIGNED) == 19
    assert set(SIGNED) == set(SIGNATURE_SNAPSHOTS)


@pytest.mark.parametrize("method", SIGNED_NAMES)
def test_every_signed_method_passes_the_ratified_recv_window(method: str) -> None:
    adapter, rest, sleep, _ = _adapter()
    call, sdk_name = SIGNED[method]
    _run(call(adapter))
    assert rest.calls[sdk_name] == 1
    assert rest.total() == 1
    assert rest.kwargs[sdk_name][0]["recv_window"] == RECV_WINDOW
    assert rest.args[sdk_name] == [()]
    assert sleep.waits == []


@pytest.mark.parametrize("method", SIGNED_NAMES)
def test_every_signed_method_without_a_policy_fails_closed(method: str) -> None:
    clock = VirtualClock()
    gate = _gate(clock)
    gate.record(ExchangeErrorCategory.IP_BANNED, None)  # the policy check comes first
    adapter, rest, sleep, _ = _adapter(clock=clock, gate=gate, policy=None)
    call, _ = SIGNED[method]
    with pytest.raises(SignedCallPolicyMissing):
        _run(call(adapter))
    assert rest.total() == 0
    assert sleep.waits == []


@pytest.mark.parametrize("method", SIGNED_NAMES)
@pytest.mark.parametrize(
    ("category", "refusal"),
    [
        (ExchangeErrorCategory.IP_BANNED, RateLimitBanActive),
        (ExchangeErrorCategory.RATE_LIMITED, RateLimitPauseActive),
    ],
    ids=["after_418", "after_429"],
)
def test_every_signed_method_is_refused_by_the_shared_gate(
    method: str, category: ExchangeErrorCategory, refusal: type[RestGateRefusal]
) -> None:
    adapter, rest, sleep, gate = _adapter()
    assert gate is not None
    gate.record(category, None)
    call, _ = SIGNED[method]
    with pytest.raises(refusal):
        _run(call(adapter))
    assert rest.total() == 0
    assert sleep.waits == []


@pytest.mark.parametrize("method", SIGNED_NAMES)
def test_public_signature_is_unchanged(method: str) -> None:
    signature = inspect.signature(getattr(BinanceUsdmAdapter, method))
    observed = tuple((p.name, p.kind.name) for p in signature.parameters.values())
    assert observed == SIGNATURE_SNAPSHOTS[method]


# --------------------------------------------------------------------------- #
# No signed call is retried because of a 429 or a 418; the gate refuses every method.
# --------------------------------------------------------------------------- #

RATE_LIMIT_CASES: list[tuple[str, Callable[[], BaseException], type[RestGateRefusal], int]] = [
    (
        "429_retry_after_none",
        lambda: TooManyRequestsError("slow down", -1003, None),
        RateLimitPauseActive,
        WAIT_429,
    ),
    (
        "429_retry_after_below_cap",
        lambda: TooManyRequestsError("slow down", -1003, CAP - 1),
        RateLimitPauseActive,
        CAP - 1,
    ),
    (
        "418_retry_after_none",
        lambda: RateLimitBanError("banned", -1003, None),
        RateLimitBanActive,
        WAIT_418,
    ),
]


@pytest.mark.parametrize("method", SIGNED_NAMES)
@pytest.mark.parametrize(
    ("case", "make", "refusal", "wait"),
    RATE_LIMIT_CASES,
    ids=[c[0] for c in RATE_LIMIT_CASES],
)
def test_signed_methods_never_retry_429_or_418(
    method: str,
    case: str,
    make: Callable[[], BaseException],
    refusal: type[RestGateRefusal],
    wait: int,
) -> None:
    clock = VirtualClock()
    adapter, rest, sleep, gate = _adapter(clock=clock)
    assert gate is not None
    call, sdk_name = SIGNED[method]
    exc = make()
    rest.fail(sdk_name, exc, make(), make())
    with pytest.raises(type(exc)) as info:
        _run(call(adapter))
    assert info.value is exc, case
    assert rest.calls[sdk_name] == 1, case
    assert rest.total() == 1, case
    assert sleep.waits == [], case
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.remaining_seconds == wait, case
    end = restriction.until_utc
    # Every one of the eighteen methods, placements included, is refused without sending.
    for name in SIGNED_NAMES:
        other, _ = SIGNED[name]
        with pytest.raises(refusal):
            _run(other(adapter))
    assert rest.total() == 1, case
    clock.now = end - timedelta(microseconds=1)
    with pytest.raises(refusal):
        _run(_place_entry(adapter))
    assert rest.total() == 1, case
    clock.now = end
    rest.script.clear()
    _run(_place_entry(adapter))
    assert rest.calls["new_order"] == (2 if sdk_name == "new_order" else 1), case
    assert sleep.waits == [], case


# --------------------------------------------------------------------------- #
# Quick task 261020-g1a: a -1008 (system-level throttle, HTTP 400) is NOT a 429. It is
# re-raised unchanged after one call, never retried, and never recorded in the gate, so the
# protective stop, the cancels and every read of the process keep reaching the exchange.
# --------------------------------------------------------------------------- #


def _throttled() -> BadRequestError:
    return BadRequestError("Request throttled by system-level protection.", -1008)


def test_1008_on_the_entry_leaves_the_gate_open_for_every_signed_method() -> None:
    adapter, rest, sleep, gate = _adapter()
    assert gate is not None
    throttled = _throttled()
    rest.fail("new_order", throttled, _throttled())
    with pytest.raises(BadRequestError) as info:
        _run(_place_entry(adapter))
    assert info.value is throttled
    assert rest.calls["new_order"] == 1  # one POST, never re-sent
    assert sleep.waits == []
    assert gate.restriction() is None
    assert gate.remaining_seconds() == 0
    rest.script.clear()
    # The protective stop, both cancels, the queries and the snapshots all reach the SDK.
    for name in SIGNED_NAMES:
        call, sdk_name = SIGNED[name]
        before = rest.calls[sdk_name]
        _run(call(adapter))
        assert rest.calls[sdk_name] == before + 1, name
    assert gate.restriction() is None


@pytest.mark.parametrize("method", SIGNED_NAMES)
def test_1008_on_any_signed_method_is_never_recorded_nor_retried(method: str) -> None:
    adapter, rest, sleep, gate = _adapter()
    assert gate is not None
    call, sdk_name = SIGNED[method]
    throttled = _throttled()
    rest.fail(sdk_name, throttled, _throttled(), _throttled())
    with pytest.raises(BadRequestError) as info:
        _run(call(adapter))
    assert info.value is throttled
    assert rest.calls[sdk_name] == 1
    assert rest.total() == 1
    assert sleep.waits == []
    assert gate.restriction() is None


def test_a_real_429_after_a_1008_still_pauses_everything() -> None:
    """The fix narrows nothing about a 429: it still pauses every method, placements included."""
    adapter, rest, _, gate = _adapter()
    assert gate is not None
    rest.fail("new_order", _throttled())
    with pytest.raises(BadRequestError):
        _run(_place_entry(adapter))
    assert gate.restriction() is None
    rest.fail("query_order", TooManyRequestsError("slow down", -1003, None))
    with pytest.raises(TooManyRequestsError):
        _run(_query_order(adapter))
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.reason == RATE_LIMIT_PAUSE_429
    assert restriction.remaining_seconds == WAIT_429
    for name in SIGNED_NAMES:
        other, _ = SIGNED[name]
        with pytest.raises(RateLimitPauseActive):
            _run(other(adapter))


# --------------------------------------------------------------------------- #
# -1021 on every signed method, the cancels included: the hook once, no retry.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", SIGNED_NAMES)
def test_clock_skew_on_every_signed_method_is_never_retried(method: str) -> None:
    hook = RecordingHook()
    adapter, rest, sleep, gate = _adapter(on_clock_skew=hook)
    assert gate is not None
    call, sdk_name = SIGNED[method]
    skew = BadRequestError("outside of the recvWindow", -1021)
    rest.fail(sdk_name, skew, BadRequestError("again", -1021))
    with pytest.raises(BadRequestError) as info:
        _run(call(adapter))
    assert info.value is skew
    assert hook.calls == 1
    assert rest.calls[sdk_name] == 1
    assert rest.total() == 1
    assert sleep.waits == []
    assert gate.restriction() is None


# --------------------------------------------------------------------------- #
# The drift guard blocks new entries only.
# --------------------------------------------------------------------------- #


def _allow(guard: ClockDriftGuard, clock: VirtualClock) -> None:
    guard.record(
        evaluate_clock_drift(
            before_ms=0,
            server_ms=0,
            after_ms=0,
            limits=guard.limits,
            measured_at_utc=clock(),
        )
    )


def _block(guard: ClockDriftGuard, clock: VirtualClock, reason: DriftBlockReason) -> None:
    limits = guard.limits
    if reason is DriftBlockReason.NEVER_MEASURED:
        return
    if reason is DriftBlockReason.MEASUREMENT_FAILED:
        guard.record(DriftVerdict.failed(failure_type="NetworkError", measured_at_utc=clock()))
        return
    if reason is DriftBlockReason.OUT_OF_LIMITS:
        guard.record(
            evaluate_clock_drift(
                before_ms=limits.ahead_limit_ms * 10,
                server_ms=0,
                after_ms=limits.ahead_limit_ms * 10,
                limits=limits,
                measured_at_utc=clock(),
            )
        )
        return
    _allow(guard, clock)
    clock.advance(limits.max_measurement_age_seconds + 1)


def test_clock_skew_hook_can_be_the_drift_guard() -> None:
    guard = ClockDriftGuard(limits=test_only_drift_limits())
    clock = VirtualClock()
    _allow(guard, clock)
    adapter, rest, _, _ = _adapter(
        clock=clock, drift_guard=guard, on_clock_skew=guard.note_clock_skew_error
    )
    rest.fail("query_order", BadRequestError("skew", -1021))
    with pytest.raises(BadRequestError):
        _run(_query_order(adapter))
    assert guard.remeasure_requested is True
    assert guard.blocked_reason(clock()) is DriftBlockReason.STALE
    with pytest.raises(EntriesBlocked):
        _run(_place_entry(adapter))
    assert rest.calls["new_order"] == 0


@pytest.mark.parametrize("reason", list(DriftBlockReason), ids=[r.value for r in DriftBlockReason])
def test_place_entry_raises_entries_blocked_before_any_sdk_call(reason: DriftBlockReason) -> None:
    clock = VirtualClock()
    guard = ClockDriftGuard(limits=test_only_drift_limits())
    _block(guard, clock, reason)
    assert guard.blocked_reason(clock()) is reason
    adapter, rest, sleep, gate = _adapter(clock=clock, drift_guard=guard)
    with pytest.raises(EntriesBlocked) as info:
        _run(_place_entry(adapter))
    assert info.value.reason is reason
    assert rest.total() == 0
    assert sleep.waits == []
    assert gate is not None
    assert gate.restriction() is None


def test_place_entry_runs_while_the_guard_allows() -> None:
    clock = VirtualClock()
    guard = ClockDriftGuard(limits=test_only_drift_limits())
    _allow(guard, clock)
    adapter, rest, _, _ = _adapter(clock=clock, drift_guard=guard)
    result = _run(_place_entry(adapter))
    assert result.client_order_id == ENTRY_ID
    assert rest.calls["new_order"] == 1
    assert rest.kwargs["new_order"][0]["recv_window"] == RECV_WINDOW


def test_the_policy_check_comes_before_the_drift_guard() -> None:
    clock = VirtualClock()
    guard = ClockDriftGuard(limits=test_only_drift_limits())
    rest = RecordingRest()
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        drift_guard=guard,
        clock=clock,
    )
    with pytest.raises(SignedCallPolicyMissing):
        _run(_place_entry(adapter))
    assert rest.total() == 0


@pytest.mark.parametrize("method", [n for n in SIGNED_NAMES if n != "place_entry"])
def test_only_place_entry_consults_the_drift_guard(method: str) -> None:
    clock = VirtualClock()
    guard = ClockDriftGuard(limits=test_only_drift_limits())  # never measured: blocks entries
    assert guard.entries_allowed(clock()) is False
    adapter, rest, _, _ = _adapter(clock=clock, drift_guard=guard)
    call, sdk_name = SIGNED[method]
    _run(call(adapter))
    assert rest.calls[sdk_name] == 1


@pytest.mark.parametrize("method", SIGNED_NAMES)
def test_without_a_drift_guard_nothing_is_blocked(method: str) -> None:
    adapter, rest, _, _ = _adapter()
    call, sdk_name = SIGNED[method]
    _run(call(adapter))
    assert rest.calls[sdk_name] == 1


# --------------------------------------------------------------------------- #
# The end of a ban or a pause never touches the drift guard or re-enables entries.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "make",
    [
        lambda: RateLimitBanError("banned", -1003, None),
        lambda: TooManyRequestsError("slow down", -1003, None),
    ],
    ids=["418", "429"],
)
def test_restriction_expiry_does_not_touch_drift_guard_or_entries(
    make: Callable[[], BaseException],
) -> None:
    clock = VirtualClock()
    guard = ClockDriftGuard(limits=test_only_drift_limits())
    _block(guard, clock, DriftBlockReason.MEASUREMENT_FAILED)
    hook = RecordingHook()
    adapter, rest, sleep, gate = _adapter(clock=clock, drift_guard=guard, on_clock_skew=hook)
    assert gate is not None
    exc = make()
    rest.fail("cancel_order", exc)
    with pytest.raises(type(exc)):
        _run(adapter.cancel_normal_order(symbol="BTCUSDT", orig_client_order_id=ENTRY_ID))
    restriction = gate.restriction()
    assert restriction is not None
    verdict_before = guard.last_verdict
    reason_before = guard.blocked_reason(clock())
    requested_before = guard.remeasure_requested
    calls_before = Counter(rest.calls)
    clock.now = restriction.until_utc + timedelta(seconds=1)
    assert gate.restriction() is None
    assert rest.calls == calls_before
    assert guard.last_verdict is verdict_before
    assert guard.blocked_reason(clock()) is reason_before
    assert guard.entries_allowed(clock()) is False
    assert guard.remeasure_requested is requested_before
    assert hook.calls == 0
    with pytest.raises(EntriesBlocked) as info:
        _run(_place_entry(adapter))
    assert info.value.reason is DriftBlockReason.MEASUREMENT_FAILED
    assert rest.calls["new_order"] == 0
    assert rest.calls == calls_before
    assert sleep.waits == []


# --------------------------------------------------------------------------- #
# The drift guard's time source shares the gate.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("category", "refusal"),
    [
        (ExchangeErrorCategory.IP_BANNED, RateLimitBanActive),
        (ExchangeErrorCategory.RATE_LIMITED, RateLimitPauseActive),
    ],
    ids=["ban", "pause"],
)
def test_drift_time_source_shares_gate(
    category: ExchangeErrorCategory, refusal: type[RestGateRefusal]
) -> None:
    clock = VirtualClock()
    guard = ClockDriftGuard(limits=test_only_drift_limits())
    _allow(guard, clock)
    adapter, rest, sleep, gate = _adapter(clock=clock, drift_guard=guard)
    assert gate is not None
    gate.record(category, None)
    ticks = iter([1_000, 1_002])
    verdict = _run(
        measure_clock_drift(
            server_time=adapter.server_time,
            clock_ms=lambda: next(ticks),
            now_utc=clock,
            limits=guard.limits,
        )
    )
    assert verdict.measurement_failed is True
    assert verdict.failure_type == refusal.__name__
    assert rest.calls["check_server_time"] == 0
    guard.record(verdict)
    with pytest.raises(EntriesBlocked) as info:
        _run(_place_entry(adapter))
    assert info.value.reason is DriftBlockReason.MEASUREMENT_FAILED
    assert rest.total() == 0
    assert sleep.waits == []


# --------------------------------------------------------------------------- #
# A protective order blocked by a pause or a ban is an unprotected position.
# --------------------------------------------------------------------------- #


def _attach_inputs() -> dict[str, Any]:
    """The plan 19-16 attach inputs: a resting entry (BTCUSDT LONG, COMPLETE snapshot), the REST
    position 0.010 and a time inside the snapshot TTL. TEST_ONLY numbers."""
    from decimal import Decimal

    from tests.support.protection_doubles import (
        TEST_ONLY_REGISTERED_AT,
        resting_entry_for_tests,
    )

    return {
        "entry": resting_entry_for_tests(),
        "position_quantity": Decimal("0.010"),
        "live_lot_filters": None,
        "now_utc": TEST_ONLY_REGISTERED_AT + timedelta(minutes=1),
    }


class _RecordingSafeMode:
    def __init__(self) -> None:
        self.entered_reasons: list[str] = []

    def enter_safe_mode(self, *, reason: str, now_utc: Any = None) -> None:
        self.entered_reasons.append(reason)


def _pause_before(gate: RestRateLimitGate, rest: RecordingRest) -> None:
    gate.record(ExchangeErrorCategory.RATE_LIMITED, None)


def _ban_before(gate: RestRateLimitGate, rest: RecordingRest) -> None:
    gate.record(ExchangeErrorCategory.IP_BANNED, None)


def _place_answers_429(gate: RestRateLimitGate, rest: RecordingRest) -> None:
    rest.fail("new_algo_order", TooManyRequestsError("slow down", -1003, None))


def _place_answers_418(gate: RestRateLimitGate, rest: RecordingRest) -> None:
    rest.fail("new_algo_order", RateLimitBanError("banned", -1003, None))


def _confirmation_query_refused(gate: RestRateLimitGate, rest: RecordingRest) -> None:
    # TP1 is placed; another holder of the one gate then meets a 429, so the confirmation
    # query-by-ID of TP1 is refused by the pause before it is sent.
    rest.side_effects["new_algo_order"] = lambda: _pause_before(gate, rest)


# (case, setup, expected type name, failing role, new_algo_order calls, query calls)
PROTECTIVE_CASES: list[
    tuple[str, Callable[[RestRateLimitGate, RecordingRest], None], str, str, int, int]
] = [
    ("paused_before_attach", _pause_before, "RateLimitPauseActive", "STOP_LOSS", 0, 0),
    ("banned_before_attach", _ban_before, "RateLimitBanActive", "STOP_LOSS", 0, 0),
    ("new_algo_order_429", _place_answers_429, "TooManyRequestsError", "TAKE_PROFIT_1", 1, 2),
    ("new_algo_order_418", _place_answers_418, "RateLimitBanError", "TAKE_PROFIT_1", 1, 2),
    (
        "confirmation_query_paused",
        _confirmation_query_refused,
        "RateLimitPauseActive",
        "TAKE_PROFIT_1",
        1,
        2,
    ),
]


@pytest.mark.parametrize(
    ("case", "setup", "type_name", "role", "placements", "queries"),
    PROTECTIVE_CASES,
    ids=[c[0] for c in PROTECTIVE_CASES],
)
def test_protective_blocked_by_pause_or_ban_surfaces_unprotected_position(
    case: str,
    setup: Callable[[RestRateLimitGate, RecordingRest], None],
    type_name: str,
    role: str,
    placements: int,
    queries: int,
) -> None:
    from src.execution.manager import attach_protectives_to_fill

    clock = VirtualClock()
    adapter, rest, sleep, gate = _adapter(clock=clock)
    assert gate is not None
    # Plan 19-16: attach adopts the REST-confirmed stop (the first query answers NEW) and then
    # places the take profits; no take-profit leg exists yet (every later query answers -2013).
    rest.absent_after["query_algo_order"] = 1
    setup(gate, rest)
    safe_mode = _RecordingSafeMode()
    outcome = _run(
        attach_protectives_to_fill(
            adapter=adapter,  # type: ignore[arg-type]
            safe_mode_controller=safe_mode,
            intent_store=InMemoryExecutionIntentStore(),
            **_attach_inputs(),
        )
    )
    assert outcome.is_no_trade is True, case
    assert outcome.reason_code == "ENTRY_WITHOUT_PROTECTIVE", case
    assert safe_mode.entered_reasons == ["ENTRY_WITHOUT_PROTECTIVE"], case
    assert outcome.failure_detail is not None
    assert outcome.failure_detail.startswith(f"{role}: "), outcome.failure_detail
    assert outcome.failure_detail.endswith(type_name), outcome.failure_detail
    assert role not in outcome.placed_legs, case
    assert rest.calls["new_algo_order"] == placements, case
    assert rest.calls["query_algo_order"] == queries, case
    assert rest.total() == placements + queries, case
    assert sleep.waits == [], case
    for kwargs in rest.kwargs.get("new_algo_order", []):
        assert kwargs["recv_window"] == RECV_WINDOW


# --------------------------------------------------------------------------- #
# SDK parameter-name contract: the keyword arguments bind to the installed SDK.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", SIGNED_NAMES)
def test_sdk_keyword_arguments_bind_to_the_installed_sdk(method: str) -> None:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.rest_api import (
        DerivativesTradingUsdsFuturesRestAPI,
    )

    adapter, rest, _, _ = _adapter()
    call, sdk_name = SIGNED[method]
    _run(call(adapter))
    kwargs = rest.kwargs[sdk_name][0]
    assert rest.args[sdk_name] == [()]
    sdk_signature = inspect.signature(getattr(DerivativesTradingUsdsFuturesRestAPI, sdk_name))
    assert "recv_window" in sdk_signature.parameters
    sdk_signature.bind(None, **kwargs)  # a renamed or missing SDK parameter raises TypeError
    assert kwargs["recv_window"] == RECV_WINDOW


def test_user_commission_rate_passes_symbol_by_keyword() -> None:
    adapter, rest, _, _ = _adapter()
    rates = _run(adapter.user_commission_rate("BTCUSDT"))
    assert rates.symbol == "BTCUSDT"
    assert rest.args["user_commission_rate"] == [()]
    assert rest.kwargs["user_commission_rate"] == [
        {"symbol": "BTCUSDT", "recv_window": RECV_WINDOW}
    ]


# --------------------------------------------------------------------------- #
# AST: only `_sdk_call` sends a signed SDK method to a worker thread.
# --------------------------------------------------------------------------- #

ADAPTER_SOURCE = Path(__file__).resolve().parents[1] / "src" / "adapters" / "binance_usdm.py"
SIGNED_SDK_NAMES = frozenset(sdk for _, sdk in SIGNED.values())
_SEND_HELPERS = frozenset({"to_thread", "_gated_rest_call"})


def _is_signed_sdk_attribute(node: ast.AST) -> bool:
    """`self._sdk.rest_api.<signed name>`."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr in SIGNED_SDK_NAMES
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "rest_api"
        and isinstance(node.value.value, ast.Attribute)
        and node.value.value.attr == "_sdk"
    )


def _callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def signed_send_violations(source: str) -> list[str]:
    """Methods of BinanceUsdmAdapter other than `_sdk_call` that send a signed SDK method.

    A violation is a `to_thread(...)` or `_gated_rest_call(...)` call outside `_sdk_call`,
    or a signed SDK attribute used anywhere except as the method argument of
    `self._sdk_call(...)`.
    """
    tree = ast.parse(source)
    found: list[str] = []
    for cls in tree.body:
        if not (isinstance(cls, ast.ClassDef) and cls.name == "BinanceUsdmAdapter"):
            continue
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if method.name == "_sdk_call":
                continue
            allowed: set[int] = set()
            for node in ast.walk(method):
                if isinstance(node, ast.Call) and _callee_name(node) == "_sdk_call":
                    allowed.update(id(arg) for arg in node.args[1:2])
            parents = {
                child: parent
                for parent in ast.walk(method)
                for child in ast.iter_child_nodes(parent)
            }
            for node in ast.walk(method):
                if isinstance(node, ast.Call) and _callee_name(node) in _SEND_HELPERS:
                    found.append(f"{method.name}: {_callee_name(node)}")
                if isinstance(node, ast.Attribute) and _is_signed_sdk_attribute(node):
                    if id(node) not in allowed:
                        found.append(f"{method.name}: {node.attr}")
                # `rest_api` may only be used as the base of `.rest_api.<name>`: an alias
                # (`rest = self._sdk.rest_api`) or `getattr(<...>.rest_api, name)` would reach a
                # signed method without the attribute chain the checks above look for.
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "rest_api"
                    and not isinstance(parents.get(node), ast.Attribute)
                ):
                    found.append(f"{method.name}: rest_api used other than as a base")
    return found


def test_only_the_helper_sends_signed_sdk_methods() -> None:
    assert signed_send_violations(ADAPTER_SOURCE.read_text(encoding="utf-8")) == []


def test_the_send_guard_reports_a_bypass() -> None:
    snippet = (
        "class BinanceUsdmAdapter:\n"
        "    async def _sdk_call(self, kind, method, **kw):\n"
        "        return await asyncio.to_thread(method, **kw)\n"
        "    async def good(self):\n"
        "        return await self._sdk_call(K, self._sdk.rest_api.query_order, symbol='X')\n"
        "    async def bad_thread(self):\n"
        "        return await asyncio.to_thread(self._sdk.rest_api.new_order, symbol='X')\n"
        "    async def bad_gated(self):\n"
        "        return await _gated_rest_call(g, K, self._sdk.rest_api.cancel_order)\n"
        "    def bad_direct(self):\n"
        "        return self._sdk.rest_api.new_algo_order(symbol='X')\n"
    )
    assert sorted(signed_send_violations(snippet)) == sorted(
        [
            "bad_thread: to_thread",
            "bad_thread: new_order",
            "bad_gated: _gated_rest_call",
            "bad_gated: cancel_order",
            "bad_direct: new_algo_order",
        ]
    )


def test_the_send_guard_reports_an_alias_and_a_getattr_of_rest_api() -> None:
    snippet = (
        "class BinanceUsdmAdapter:@@"
        "    async def _sdk_call(self, kind, method, **kw):@@"
        "        return await asyncio.to_thread(method, **kw)@@"
        "    def bad_alias(self):@@"
        "        rest = self._sdk.rest_api@@"
        "        return rest.new_order(symbol='X')@@"
        "    def bad_getattr(self, name):@@"
        "        return getattr(self._sdk.rest_api, name)(symbol='X')@@"
        "    def fine_unsigned(self):@@"
        "        return self._sdk.rest_api.exchange_information@@"
    ).replace("@@", chr(10))
    assert sorted(signed_send_violations(snippet)) == [
        "bad_alias: rest_api used other than as a base",
        "bad_getattr: rest_api used other than as a base",
    ]
