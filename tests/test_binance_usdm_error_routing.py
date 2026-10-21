"""Error routing of BinanceUsdmAdapter through the taxonomy and the shared REST gate (plan 18-10).

* cancel retries only STATUS_UNKNOWN (5xx, 408, network errors, -1006, -1007) within the four
  `_RECONCILER_CANCEL_*` ceilings; a 429, a 418, a definitive rejection, an auth error or an
  unknown error fails after one SDK call; ORDER_ABSENT is success;
* nothing is retried because of a 418 or a 429 (user record 18-DEC-O-18-01.md and its
  amendment of 2026-10-16); a 418 bans and a 429 pauses every REST call of every holder of
  the one gate, placements included, without sending;
* placement makes exactly one SDK call for every error class (D-11, 09-REVIEW CR-09);
* the end of a ban or a pause sends, replays and reports nothing.

No test sleeps: the adapter gets a recording sleep and `asyncio.sleep` is patched to fail.
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
import src.adapters.binance_usdm as usdm_mod
import tenacity
from binance_common.errors import (
    BadRequestError,
    ClientError,
    NetworkError,
    RateLimitBanError,
    ServerError,
    TooManyRequestsError,
)
from src.adapters.binance_limits import RateLimitPolicy
from src.adapters.binance_ratelimit_gate import (
    RateLimitBanActive,
    RateLimitPauseActive,
    RestGateRefusal,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import BinanceUsdmAdapter
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
from tests.support.limits import test_only_signed_call_policy

MAX_ATTEMPTS = usdm_mod._RECONCILER_CANCEL_MAX_ATTEMPTS
WAIT_MULTIPLIER_SECONDS = usdm_mod._RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS
WAIT_MAX_SECONDS = usdm_mod._RECONCILER_CANCEL_WAIT_MAX_SECONDS
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


def _gate(clock: VirtualClock) -> RestRateLimitGate:
    policy = RateLimitPolicy(
        no_retry_after_wait_418_seconds=WAIT_418,
        no_retry_after_wait_429_seconds=WAIT_429,
        retry_after_cap_seconds=CAP,
    )
    return RestRateLimitGate(policy=policy, clock=clock)


# --------------------------------------------------------------------------- #
# SDK-shaped fake: counting REST callables, scripted exceptions, response objects.
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


class ScriptedRest:
    """Each SDK REST method counts calls and raises the next scripted exception, if any."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.script: dict[str, list[BaseException]] = {}
        self.side_effects: dict[str, Callable[[], None]] = {}

    def fail(self, name: str, *excs: BaseException) -> None:
        self.script.setdefault(name, []).extend(excs)

    def total(self) -> int:
        return sum(self.calls.values())

    def __getattr__(self, name: str) -> Any:
        if name not in SDK_NAMES:
            raise AttributeError(name)

        def _call(*_: Any, **kwargs: Any) -> _Response:
            self.calls[name] += 1
            effect = self.side_effects.pop(name, None)
            if effect is not None:
                effect()
            queue = self.script.get(name)
            if queue:
                raise queue.pop(0)
            return _Response(_payloads(kwargs)[name])

        return _call


def _adapter(
    gate: RestRateLimitGate | None = None,
) -> tuple[BinanceUsdmAdapter, ScriptedRest, RecordingSleep]:
    # Plan 18-13: a signed call needs the ratified SignedCallPolicy, and the policy needs the
    # shared gate, so an adapter a test builds without a gate gets a private one of its own.
    gate = gate if gate is not None else _gate(VirtualClock())
    rest = ScriptedRest()
    sleep = RecordingSleep()
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        rest_gate=gate,
        sleep=sleep,
        signed_call_policy=test_only_signed_call_policy(),
    )
    return adapter, rest, sleep


def _ungated_adapter() -> tuple[BinanceUsdmAdapter, ScriptedRest, RecordingSleep]:
    """No gate and no signed policy: only the public delegations can run (plan 18-13)."""
    rest = ScriptedRest()
    sleep = RecordingSleep()
    adapter = BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=rest),  # type: ignore[arg-type]
        sleep=sleep,
    )
    return adapter, rest, sleep


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# Every adapter method that reaches the SDK REST client, with the SDK method it calls.
METHODS: dict[str, tuple[Callable[[BinanceUsdmAdapter], Any], str]] = {
    "snapshot_open_normal_orders": (
        lambda a: a.snapshot_open_normal_orders(),
        "current_all_open_orders",
    ),
    "snapshot_open_algo_orders": (
        lambda a: a.snapshot_open_algo_orders(),
        "current_all_algo_open_orders",
    ),
    "snapshot_positions": (lambda a: a.snapshot_positions(), "position_information_v3"),
    "query_algo_order_by_client": (
        lambda a: a.query_algo_order_by_client(client_algo_id=ALGO_ID),
        "query_algo_order",
    ),
    "query_order_by_client": (
        lambda a: a.query_order_by_client(symbol="BTCUSDT", orig_client_order_id=ENTRY_ID),
        "query_order",
    ),
    "cancel_normal_order": (
        lambda a: a.cancel_normal_order(symbol="BTCUSDT", orig_client_order_id=ENTRY_ID),
        "cancel_order",
    ),
    "cancel_algo_order": (
        lambda a: a.cancel_algo_order(symbol="BTCUSDT", client_algo_id=ALGO_ID),
        "cancel_algo_order",
    ),
    "place_entry": (
        lambda a: a.place_entry(
            symbol="BTCUSDT",
            side="BUY",
            position_side="BOTH",
            time_in_force="GTC",
            quantity=Decimal("0.010"),
            price=Decimal("100.0"),
            new_client_order_id=ENTRY_ID,
        ),
        "new_order",
    ),
    "place_algo_protective": (
        lambda a: a.place_algo_protective(
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
        ),
        "new_algo_order",
    ),
    "get_position_mode": (lambda a: a.get_position_mode(), "get_current_position_mode"),
    "user_commission_rate": (lambda a: a.user_commission_rate("BTCUSDT"), "user_commission_rate"),
    "klines": (lambda a: a.klines("BTCUSDT", "1h"), "kline_candlestick_data"),
    "mark_klines": (lambda a: a.mark_klines("BTCUSDT", "1h"), "mark_price_kline_candlestick_data"),
    "open_interest": (lambda a: a.open_interest("BTCUSDT"), "open_interest"),
    "open_interest_statistics": (
        lambda a: a.open_interest_statistics("BTCUSDT", "1h"),
        "open_interest_statistics",
    ),
    "funding_rate": (lambda a: a.funding_rate("BTCUSDT"), "get_funding_rate_history"),
    "server_time": (lambda a: a.server_time(), "check_server_time"),
    "exchange_info": (lambda a: a.exchange_info(), "exchange_information"),
}
METHOD_NAMES = sorted(METHODS)
# The public-data delegations: no recvWindow, no signed policy needed (plan 18-13).
PUBLIC_METHOD_NAMES = sorted(
    {
        "klines",
        "mark_klines",
        "open_interest",
        "open_interest_statistics",
        "funding_rate",
        "server_time",
        "exchange_info",
    }
)


def test_every_method_succeeds_through_the_fake() -> None:
    adapter, rest, sleep = _adapter(_gate(VirtualClock()))
    for name in METHOD_NAMES:
        call, sdk_name = METHODS[name]
        _run(call(adapter))
        assert rest.calls[sdk_name] == 1, name
    assert sleep.waits == []


def test_constructor_keeps_positional_and_bare_use() -> None:
    sdk = SimpleNamespace(rest_api=ScriptedRest())
    adapter = BinanceUsdmAdapter(sdk)  # type: ignore[arg-type]
    assert adapter._sdk is sdk  # noqa: SLF001
    with pytest.raises(TypeError):
        BinanceUsdmAdapter(sdk, None)  # type: ignore[misc]
    gate = _gate(VirtualClock())
    gated = BinanceUsdmAdapter(sdk_client=sdk, rest_gate=gate)  # type: ignore[arg-type]
    assert gated._public._rest_gate is gate  # noqa: SLF001


# --------------------------------------------------------------------------- #
# Cancel: the retry matrix.
# --------------------------------------------------------------------------- #

CANCELS: dict[str, tuple[Callable[[BinanceUsdmAdapter], Any], str]] = {
    name: METHODS[name] for name in ("cancel_normal_order", "cancel_algo_order")
}


@pytest.mark.parametrize("method", sorted(CANCELS))
@pytest.mark.parametrize("code", [-2011, -2013])
def test_cancel_of_an_absent_order_is_success_after_one_call(method: str, code: int) -> None:
    call, sdk_name = CANCELS[method]
    adapter, rest, sleep = _adapter()
    rest.fail(sdk_name, BadRequestError("Unknown order sent.", code))
    with capture_logs() as logs:
        assert _run(call(adapter)) is None
    assert rest.calls[sdk_name] == 1
    assert sleep.waits == []
    events = [entry for entry in logs if entry["event"].endswith("already_canceled")]
    assert len(events) == 1
    assert events[0]["error_class"] == "BadRequestError"
    assert events[0]["code"] == code
    assert "Unknown order sent." not in repr(events[0])


def _fail_at_once_cases() -> list[tuple[str, Callable[[], BaseException]]]:
    return [
        ("margin_-2019", lambda: BadRequestError("Margin is insufficient.", -2019)),
        ("rejected_-2010", lambda: BadRequestError("rejected", -2010)),
        ("min_notional_-4164", lambda: BadRequestError("notional", -4164)),
        ("auth_-2014", lambda: BadRequestError("API-key format invalid.", -2014)),
        ("unlisted_code", lambda: BadRequestError("Unknown order sent.", -999_999)),
        ("runtime_error", lambda: RuntimeError("-2011 UNKNOWN_ORDER")),
        ("value_error", lambda: ValueError("bad wiring")),
        ("ban_418", lambda: RateLimitBanError("banned", -1003, None)),
        ("429_retry_after_7", lambda: TooManyRequestsError("slow down", -1003, 7)),
        ("429_retry_after_none", lambda: TooManyRequestsError("slow down", -1003, None)),
    ]


FAIL_AT_ONCE = _fail_at_once_cases()


@pytest.mark.parametrize("method", sorted(CANCELS))
@pytest.mark.parametrize(("case", "make"), FAIL_AT_ONCE, ids=[c for c, _ in FAIL_AT_ONCE])
@pytest.mark.parametrize("gated", [False, True], ids=["no_gate", "gate"])
def test_cancel_fails_at_once_for_everything_but_status_unknown(
    method: str, case: str, make: Callable[[], BaseException], gated: bool
) -> None:
    call, sdk_name = CANCELS[method]
    adapter, rest, sleep = _adapter(_gate(VirtualClock()) if gated else None)
    exc = make()
    rest.fail(sdk_name, exc)
    with pytest.raises(type(exc)) as info:
        _run(call(adapter))
    assert info.value is exc, case
    assert rest.calls[sdk_name] == 1, case
    assert sleep.waits == [], case


def _status_unknown_cases() -> list[tuple[str, Callable[[], BaseException]]]:
    return [
        ("server_503", lambda: ServerError("unavailable", 503)),
        ("network", lambda: NetworkError("reset")),
        ("client_408", lambda: ClientError("timeout", None)),
        ("unexpected_resp_-1006", lambda: BadRequestError("unexpected", -1006)),
        ("timeout_-1007", lambda: BadRequestError("timeout", -1007)),
    ]


STATUS_UNKNOWN = _status_unknown_cases()


@pytest.mark.parametrize("method", sorted(CANCELS))
@pytest.mark.parametrize(("case", "make"), STATUS_UNKNOWN, ids=[c for c, _ in STATUS_UNKNOWN])
def test_cancel_retries_status_unknown_up_to_the_ceiling(
    method: str, case: str, make: Callable[[], BaseException]
) -> None:
    call, sdk_name = CANCELS[method]
    adapter, rest, sleep = _adapter(_gate(VirtualClock()))
    excs = [make() for _ in range(MAX_ATTEMPTS)]
    rest.fail(sdk_name, *excs)
    with pytest.raises(type(excs[0])) as info:
        _run(call(adapter))
    assert info.value is excs[-1], case
    assert rest.calls[sdk_name] == MAX_ATTEMPTS, case
    assert len(sleep.waits) == MAX_ATTEMPTS - 1, case
    # Each wait is a random draw below the exponential bound of its attempt, capped at the
    # wait ceiling (review WR-08: the count alone would pass for a zero or an uncapped wait).
    for index, waited in enumerate(sleep.waits):
        bound = min(WAIT_MAX_SECONDS, WAIT_MULTIPLIER_SECONDS * 2**index)
        assert 0 <= waited <= bound, (case, index, waited)


@pytest.mark.parametrize("method", sorted(CANCELS))
def test_cancel_status_unknown_then_success(method: str) -> None:
    call, sdk_name = CANCELS[method]
    adapter, rest, sleep = _adapter()
    rest.fail(sdk_name, ServerError("unavailable", 502))
    assert _run(call(adapter)) is None
    assert rest.calls[sdk_name] == 2
    assert len(sleep.waits) == 1


@pytest.mark.parametrize("method", sorted(CANCELS))
@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [(7, 7), (None, WAIT_429), (10 * CAP, CAP)],
    ids=["retry_after_7", "retry_after_none", "retry_after_capped"],
)
def test_cancel_429_fails_at_once_and_pauses_the_gate(
    method: str, retry_after: int | None, expected: int
) -> None:
    call, sdk_name = CANCELS[method]
    clock = VirtualClock()
    gate = _gate(clock)
    adapter, rest, sleep = _adapter(gate)
    limited = TooManyRequestsError("slow down", -1003, retry_after)
    rest.fail(sdk_name, limited)
    with pytest.raises(TooManyRequestsError) as info:
        _run(call(adapter))
    assert info.value is limited
    assert rest.calls[sdk_name] == 1
    assert sleep.waits == []
    restriction = gate.restriction()
    assert restriction is not None
    assert restriction.reason == "RATE_LIMIT_PAUSE_429"
    assert restriction.remaining_seconds == expected
    with pytest.raises(RateLimitPauseActive):
        _run(call(adapter))
    assert rest.calls[sdk_name] == 1


@pytest.mark.parametrize("method", sorted(CANCELS))
@pytest.mark.parametrize(
    ("record", "refusal"),
    [
        (lambda g: g.record(ExchangeErrorCategory.RATE_LIMITED, None), RateLimitPauseActive),
        (lambda g: g.record(ExchangeErrorCategory.IP_BANNED, None), RateLimitBanActive),
    ],
    ids=["pause", "ban"],
)
def test_cancel_retry_attempt_refused_by_the_gate_is_not_retried(
    method: str,
    record: Callable[[RestRateLimitGate], Any],
    refusal: type[RestGateRefusal],
) -> None:
    """Another holder restricts the gate between two attempts: the next attempt is refused."""
    call, sdk_name = CANCELS[method]
    gate = _gate(VirtualClock())
    adapter, rest, sleep = _adapter(gate)
    rest.side_effects[sdk_name] = lambda: record(gate)
    rest.fail(sdk_name, ServerError("unavailable", 503))
    with pytest.raises(refusal):
        _run(call(adapter))
    assert rest.calls[sdk_name] == 1
    assert len(sleep.waits) == 1


# --------------------------------------------------------------------------- #
# Queries meet a 429: one call, no wait, with or without a gate.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", ["query_order_by_client", "query_algo_order_by_client"])
@pytest.mark.parametrize("gated", [False, True], ids=["no_gate", "gate"])
def test_query_429_is_a_single_attempt(method: str, gated: bool) -> None:
    call, sdk_name = METHODS[method]
    adapter, rest, sleep = _adapter(_gate(VirtualClock()) if gated else None)
    limited = TooManyRequestsError("slow down", -1003, 3)
    rest.fail(sdk_name, limited)
    with pytest.raises(TooManyRequestsError) as info:
        _run(call(adapter))
    assert info.value is limited
    assert rest.calls[sdk_name] == 1
    assert sleep.waits == []


# --------------------------------------------------------------------------- #
# One gate: a 429 pauses and a 418 bans every method of every holder.
# --------------------------------------------------------------------------- #


def _restrict_through(
    adapter: BinanceUsdmAdapter, rest: ScriptedRest, trigger: str, exc: BaseException
) -> None:
    call, sdk_name = METHODS[trigger]
    rest.fail(sdk_name, exc)
    with pytest.raises(type(exc)) as info:
        _run(call(adapter))
    assert info.value is exc
    assert rest.calls[sdk_name] == 1  # the failing request is never retried


def _assert_every_method_refused(
    adapter: BinanceUsdmAdapter, rest: ScriptedRest, refusal: type[RestGateRefusal]
) -> None:
    before = rest.total()
    for name in METHOD_NAMES:
        call, _ = METHODS[name]
        with pytest.raises(refusal):
            _run(call(adapter))
    assert rest.total() == before


@pytest.mark.parametrize("trigger", METHOD_NAMES)
def test_pause_refuses_every_method_without_sending(trigger: str) -> None:
    clock = VirtualClock()
    gate = _gate(clock)
    adapter, rest, sleep = _adapter(gate)
    _restrict_through(adapter, rest, trigger, TooManyRequestsError("slow down", -1003, None))
    _assert_every_method_refused(adapter, rest, RateLimitPauseActive)
    clock.advance(WAIT_429 - 1)
    _assert_every_method_refused(adapter, rest, RateLimitPauseActive)
    clock.advance(1)
    before = rest.calls["position_information_v3"]
    _run(adapter.snapshot_positions())
    assert rest.calls["position_information_v3"] == before + 1
    assert sleep.waits == []


@pytest.mark.parametrize("trigger", METHOD_NAMES)
def test_ban_refuses_every_method_without_sending(trigger: str) -> None:
    clock = VirtualClock()
    gate = _gate(clock)
    adapter, rest, sleep = _adapter(gate)
    _restrict_through(adapter, rest, trigger, RateLimitBanError("banned", -1003, None))
    _assert_every_method_refused(adapter, rest, RateLimitBanActive)
    clock.advance(WAIT_429)  # the 429 fallback never lifts a ban
    _assert_every_method_refused(adapter, rest, RateLimitBanActive)
    clock.advance(WAIT_418 - WAIT_429)
    before = rest.calls["get_current_position_mode"]
    _run(adapter.get_position_mode())
    assert rest.calls["get_current_position_mode"] == before + 1
    assert sleep.waits == []


@pytest.mark.parametrize(
    ("exc", "refusal"),
    [
        (TooManyRequestsError("slow down", -1003, None), RateLimitPauseActive),
        (RateLimitBanError("banned", -1003, None), RateLimitBanActive),
    ],
    ids=["429", "418"],
)
def test_two_adapters_share_one_gate(exc: BaseException, refusal: type[RestGateRefusal]) -> None:
    gate = _gate(VirtualClock())
    first, first_rest, _ = _adapter(gate)
    second, second_rest, second_sleep = _adapter(gate)
    _restrict_through(first, first_rest, "snapshot_open_algo_orders", exc)
    _assert_every_method_refused(second, second_rest, refusal)
    assert second_rest.total() == 0
    assert second_sleep.waits == []


_PLAN_20_07_RESTART_RESTORE_NAMES = frozenset(
    {"restore", "_restore_done", "_restore_lock", "recovery_status"}
)


def test_restriction_expiry_sends_and_replays_nothing() -> None:
    clock = VirtualClock()
    gate = _gate(clock)
    adapter, rest, sleep = _adapter(gate)
    limited = TooManyRequestsError("slow down", -1003, None)
    rest.fail("cancel_algo_order", limited)
    with capture_logs() as logs:
        with pytest.raises(TooManyRequestsError):
            _run(adapter.cancel_algo_order(symbol="BTCUSDT", client_algo_id=ALGO_ID))
        calls_before = Counter(rest.calls)
        clock.advance(WAIT_429 + 1)
        assert gate.check() is None
        assert gate.restriction() is None
        assert gate.remaining_seconds() == 0
    # The opening by itself sent nothing and replayed nothing.
    assert rest.calls == calls_before
    assert rest.calls["cancel_algo_order"] == 1
    assert sleep.waits == []
    for entry in logs:
        text = repr(entry).lower()
        for word in ("recover", "restor", "resum", "protected", "reopen"):
            assert word not in text, entry
    for holder in (gate, adapter):
        for name in dir(holder):
            lowered = name.lower()
            if holder is gate and name in _PLAN_20_07_RESTART_RESTORE_NAMES:
                continue  # restart restore only; never an automatic recovery after expiry
            for word in ("restor", "recover", "resum", "unban", "clear", "reset", "healthy"):
                assert word not in lowered, (type(holder).__name__, name)


# --------------------------------------------------------------------------- #
# Placement: exactly one SDK call for every error class.
# --------------------------------------------------------------------------- #


def _placement_cases() -> list[tuple[str, Callable[[], BaseException]]]:
    return [
        ("rejected_-2010", lambda: BadRequestError("rejected", -2010)),
        ("duplicate_-4116", lambda: BadRequestError("duplicate", -4116)),
        ("bad_request_none", lambda: BadRequestError("no code", None)),
        ("server_503", lambda: ServerError("unavailable", 503)),
        ("network", lambda: NetworkError("reset")),
        ("429_retry_after_3", lambda: TooManyRequestsError("slow down", -1003, 3)),
        ("429_retry_after_none", lambda: TooManyRequestsError("slow down", -1003, None)),
        ("ban_418", lambda: RateLimitBanError("banned", -1003, None)),
        ("client_error", lambda: ClientError("timeout", None)),
        ("runtime_error", lambda: RuntimeError("boom")),
        ("timeout_error", lambda: TimeoutError("read timed out")),
    ]


PLACEMENT = _placement_cases()
PLACEMENT_METHODS = ["place_entry", "place_algo_protective"]


@pytest.mark.parametrize("method", PLACEMENT_METHODS)
@pytest.mark.parametrize(("case", "make"), PLACEMENT, ids=[c for c, _ in PLACEMENT])
@pytest.mark.parametrize("gated", [False, True], ids=["no_gate", "gate"])
def test_placement_calls_the_sdk_exactly_once(
    method: str, case: str, make: Callable[[], BaseException], gated: bool
) -> None:
    call, sdk_name = METHODS[method]
    adapter, rest, sleep = _adapter(_gate(VirtualClock()) if gated else None)
    exc = make()
    rest.fail(sdk_name, exc, make(), make())
    with pytest.raises(type(exc)) as info:
        _run(call(adapter))
    assert info.value is exc, case
    assert rest.calls[sdk_name] == 1, case
    assert rest.total() == 1, case
    assert sleep.waits == [], case


@pytest.mark.parametrize("method", PLACEMENT_METHODS)
@pytest.mark.parametrize(
    ("category", "refusal"),
    [
        (ExchangeErrorCategory.RATE_LIMITED, RateLimitPauseActive),
        (ExchangeErrorCategory.IP_BANNED, RateLimitBanActive),
    ],
    ids=["pause", "ban"],
)
def test_placement_is_refused_without_sending_while_restricted(
    method: str, category: Any, refusal: type[RestGateRefusal]
) -> None:
    call, sdk_name = METHODS[method]
    gate = _gate(VirtualClock())
    gate.record(category, None)
    adapter, rest, sleep = _adapter(gate)
    with pytest.raises(refusal):
        _run(call(adapter))
    assert rest.calls[sdk_name] == 0
    assert sleep.waits == []


# --------------------------------------------------------------------------- #
# Without a gate: nothing is refused or recorded, a 418 or 429 raises after one call.
# --------------------------------------------------------------------------- #


# Plan 18-13: a signed method cannot run without the policy and the shared gate (see
# tests/test_binance_usdm_signed_calls.py), so the ungated case covers the public delegations.
@pytest.mark.parametrize("method", PUBLIC_METHOD_NAMES)
def test_without_a_gate_a_rate_limit_raises_after_one_call_and_nothing_is_refused(
    method: str,
) -> None:
    call, sdk_name = METHODS[method]
    adapter, rest, sleep = _ungated_adapter()
    for exc in (
        TooManyRequestsError("slow down", -1003, None),
        RateLimitBanError("banned", -1003, None),
    ):
        rest.fail(sdk_name, exc)
        before = rest.calls[sdk_name]
        with pytest.raises(type(exc)):
            _run(call(adapter))
        assert rest.calls[sdk_name] == before + 1
    _run(call(adapter))
    assert sleep.waits == []


@pytest.mark.parametrize("raw", [None, "false", 0])
def test_position_mode_that_is_not_a_bool_is_refused_not_read_as_one_way(raw: Any) -> None:
    """WR-09: a dropped or renamed dualSidePosition must never read as ONE_WAY."""
    adapter, rest, _ = _adapter()
    rest.get_current_position_mode = lambda **_: _Response(  # type: ignore[attr-defined]
        SimpleNamespace(dual_side_position=raw)
    )
    with pytest.raises(ValueError, match="dualSidePosition"):
        _run(adapter.get_position_mode())


def test_the_four_cancel_retry_ceilings_are_the_recorded_values() -> None:
    """Review WR-08: the ceilings are typed here, so a drift in `src` fails a test."""
    assert usdm_mod._RECONCILER_CANCEL_MAX_ATTEMPTS == 3
    assert usdm_mod._RECONCILER_CANCEL_MAX_DELAY_SECONDS == 30
    assert usdm_mod._RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS == 1
    assert usdm_mod._RECONCILER_CANCEL_WAIT_MAX_SECONDS == 10


def test_the_cancel_retry_wait_never_exceeds_the_wait_ceiling() -> None:
    adapter, _, _ = _adapter()
    retrying = adapter._cancel_retrying()
    for attempt_number in (1, 2, 3, 10, 40):
        state = tenacity.RetryCallState(retry_object=retrying, fn=None, args=(), kwargs={})
        state.attempt_number = attempt_number
        draws = [retrying.wait(state) for _ in range(200)]
        bound = min(10, 1 * 2 ** (attempt_number - 1))
        assert all(0 <= draw <= bound for draw in draws), attempt_number
    # A far attempt actually reaches the cap region (the wait is not stuck at zero or one).
    assert max(draws) > 5
