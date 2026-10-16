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

import asyncio
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from binance_common.errors import (
    BadRequestError,
    RateLimitBanError,
    TooManyRequestsError,
)
from src.adapters.binance_clock import ClockDriftGuard
from src.adapters.binance_limits import RateLimitPolicy, SignedCallPolicy
from src.adapters.binance_ratelimit_gate import (
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    RateLimitPauseActive,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter, SignedCallPolicyMissing
from src.domain.exchange_errors import ExchangeErrorCategory
from structlog.testing import capture_logs

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
    `side_effects` runs once, inside the next call of the named method, before it answers.
    """

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.kwargs: dict[str, list[dict[str, Any]]] = {}
        self.args: dict[str, list[tuple[Any, ...]]] = {}
        self.script: dict[str, list[BaseException]] = {}
        self.absent: set[str] = set()
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
            if name in self.absent:
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
